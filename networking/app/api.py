from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select, update, func
from typing import List, Dict, Set
import random

from app.database import get_db
from app.models import VlanPool, Slice, Network, VmInterface, SecurityRule, VirtualMachine
from app.schemas import (
    AllocateRequest, AllocateResponse, ReleaseRequest, VlanAvailableResponse,
    SliceNetworkResponse, OvsCommandResponse, OvsWorkerCommand, NetworkDetail, InterfaceDetail,
    SecurityRuleCreate, SecurityRuleResponse, FlowResponse, OvsFlow, NatCommandResponse, NatNetworkCommand
)

router = APIRouter()

def generate_mac() -> str:
    mac = [0x52, 0x54, 0x00,
           random.randint(0x00, 0x7f),
           random.randint(0x00, 0xff),
           random.randint(0x00, 0xff)]
    return ':'.join(f"{b:02x}" for b in mac)

@router.post("/networking/allocate", response_model=AllocateResponse)
async def allocate(request: AllocateRequest, db: AsyncSession = Depends(get_db)):
    result = await db.execute(select(Slice).where(Slice.id == request.slice_id))
    slice_obj = result.scalar_one_or_none()
    if not slice_obj:
        raise HTTPException(status_code=400, detail="Slice not found")

    if not slice_obj.vlan_slice:
        vlan_result = await db.execute(select(VlanPool).where(VlanPool.status == 'AVAILABLE').limit(1))
        vlan_row = vlan_result.scalar_one_or_none()
        if not vlan_row:
            raise HTTPException(status_code=409, detail="No VLANs available in pool")
        
        vlan_row.status = 'USED'
        slice_obj.vlan_slice = vlan_row.vlan_id
        await db.flush()
    
    vlan_slice = slice_obj.vlan_slice
    bridge_name = f"br-sl-{request.slice_id}"

    networks_response = []
    current_vlan_inner = 100

    for idx, link in enumerate(request.links):
        worker_a = request.placement_map.get(str(link.vm_a_id))
        worker_b = request.placement_map.get(str(link.vm_b_id))
        
        if worker_a is None or worker_b is None:
            raise HTTPException(status_code=400, detail="Incomplete placement_map")

        is_remote = (worker_a != worker_b)
        vlan_inner = current_vlan_inner
        current_vlan_inner += 100

        subnet_base = f"10.{vlan_slice % 256}.{idx + 1}"
        subnet_cidr = f"{subnet_base}.0/24"
        
        net = Network(
            slice_id=request.slice_id,
            vlan_inner=vlan_inner,
            subnet_cidr=subnet_cidr,
            is_remote=is_remote,
            internet_access=link.internet_access
        )
        db.add(net)
        await db.flush()

        ip_a = f"{subnet_base}.1"
        mac_a = generate_mac()
        tap_a = f"tap-vm{link.vm_a_id}-{link.iface_a}"
        
        iface_a = VmInterface(
            vm_id=link.vm_a_id,
            network_id=net.id,
            mac_address=mac_a,
            ip_address=ip_a,
            interface_name=link.iface_a,
            tap_name=tap_a
        )
        db.add(iface_a)

        ip_b = f"{subnet_base}.2"
        mac_b = generate_mac()
        tap_b = f"tap-vm{link.vm_b_id}-{link.iface_b}"
        
        iface_b = VmInterface(
            vm_id=link.vm_b_id,
            network_id=net.id,
            mac_address=mac_b,
            ip_address=ip_b,
            interface_name=link.iface_b,
            tap_name=tap_b
        )
        db.add(iface_b)

        networks_response.append(NetworkDetail(
            network_id=net.id,
            id=net.id,
            link_name=link.link_name,
            vlan_inner=vlan_inner,
            subnet_cidr=subnet_cidr,
            is_remote=is_remote,
            internet_access=net.internet_access,
            interfaces=[
                InterfaceDetail(vm_id=link.vm_a_id, interface_name=link.iface_a, tap_name=tap_a, ip_address=ip_a, mac_address=mac_a, worker_id=worker_a),
                InterfaceDetail(vm_id=link.vm_b_id, interface_name=link.iface_b, tap_name=tap_b, ip_address=ip_b, mac_address=mac_b, worker_id=worker_b)
            ]
        ))

    await db.commit()

    return AllocateResponse(
        slice_id=request.slice_id,
        vlan_slice=vlan_slice,
        bridge_name=bridge_name,
        networks=networks_response
    )

@router.post("/networking/release")
async def release(request: ReleaseRequest, db: AsyncSession = Depends(get_db)):
    result = await db.execute(select(Slice).where(Slice.id == request.slice_id))
    slice_obj = result.scalar_one_or_none()
    
    if not slice_obj:
        return {"status": "ignored"}

    released_vlan = slice_obj.vlan_slice

    nets_res = await db.execute(select(Network).where(Network.slice_id == request.slice_id))
    networks = nets_res.scalars().all()
    net_ids = [n.id for n in networks]
    
    ifaces_deleted = 0
    if net_ids:
        ifaces_res = await db.execute(select(VmInterface).where(VmInterface.network_id.in_(net_ids)))
        ifaces = ifaces_res.scalars().all()
        ifaces_deleted = len(ifaces)
        for iface in ifaces:
            await db.delete(iface)

    networks_deleted = len(networks)
    for net in networks:
        await db.delete(net)

    if released_vlan:
        await db.execute(update(VlanPool).where(VlanPool.vlan_id == released_vlan).values(status='AVAILABLE'))
        slice_obj.vlan_slice = None

    await db.commit()

    return {
        "released_vlan_slice": released_vlan,
        "networks_deleted": networks_deleted,
        "interfaces_deleted": ifaces_deleted
    }

@router.get("/networking/vlans/available", response_model=VlanAvailableResponse)
async def vlans_available(db: AsyncSession = Depends(get_db)):
    total = await db.scalar(select(func.count(VlanPool.vlan_id)))
    available = await db.scalar(select(func.count(VlanPool.vlan_id)).where(VlanPool.status == 'AVAILABLE'))
    used = total - available
    return {"total": total, "available": available, "used": used}

@router.get("/networking/networks/{slice_id}", response_model=SliceNetworkResponse)
async def get_networks(slice_id: int, db: AsyncSession = Depends(get_db)):
    slice_res = await db.execute(select(Slice).where(Slice.id == slice_id))
    slice_obj = slice_res.scalar_one_or_none()
    if not slice_obj:
        raise HTTPException(status_code=404, detail="Slice not found")

    nets_res = await db.execute(select(Network).where(Network.slice_id == slice_id))
    networks = nets_res.scalars().all()

    vms_res = await db.execute(select(VirtualMachine).where(VirtualMachine.slice_id == slice_id))
    vms = {vm.id: vm.worker_id for vm in vms_res.scalars().all()}

    network_details = []
    for net in networks:
        ifaces_res = await db.execute(select(VmInterface).where(VmInterface.network_id == net.id))
        ifaces = ifaces_res.scalars().all()
        
        interfaces = []
        for iface in ifaces:
            interfaces.append(InterfaceDetail(
                vm_id=iface.vm_id,
                worker_id=vms.get(iface.vm_id),
                mac_address=iface.mac_address,
                ip_address=iface.ip_address,
                interface_name=iface.interface_name,
                tap_name=iface.tap_name
            ))
            
        network_details.append(NetworkDetail(
            id=net.id,
            vlan_inner=net.vlan_inner,
            subnet_cidr=net.subnet_cidr,
            is_remote=net.is_remote,
            internet_access=net.internet_access,
            interfaces=interfaces
        ))

    return SliceNetworkResponse(
        slice_id=slice_id,
        vlan_slice=slice_obj.vlan_slice or 0,
        bridge_name=f"br-sl-{slice_id}",
        networks=network_details
    )

@router.get("/networking/ovs/commands/{slice_id}", response_model=OvsCommandResponse)
async def ovs_commands(slice_id: int, db: AsyncSession = Depends(get_db)):
    slice_res = await db.execute(select(Slice).where(Slice.id == slice_id))
    slice_obj = slice_res.scalar_one_or_none()
    if not slice_obj or not slice_obj.vlan_slice:
        raise HTTPException(status_code=404, detail="Slice or VLAN not found")

    vlan_slice = slice_obj.vlan_slice
    bridge_name = f"br-sl-{slice_id}"

    nets_res = await db.execute(select(Network).where(Network.slice_id == slice_id))
    networks = nets_res.scalars().all()
    
    if not networks:
        return OvsCommandResponse(slice_id=slice_id, vlan_slice=vlan_slice, bridge_name=bridge_name, workers=[])

    net_map = {n.id: n for n in networks}

    ifaces_res = await db.execute(select(VmInterface).where(VmInterface.network_id.in_(net_map.keys())))
    ifaces = ifaces_res.scalars().all()

    vms_res = await db.execute(select(VirtualMachine).where(VirtualMachine.slice_id == slice_id))
    vm_workers = {vm.id: vm.worker_id for vm in vms_res.scalars().all()}

    worker_ifaces = {}
    workers_with_remote = set()
    
    for iface in ifaces:
        wid = vm_workers.get(iface.vm_id)
        if wid is None:
            continue
        worker_ifaces.setdefault(wid, []).append(iface)
        net = net_map.get(iface.network_id)
        if net and net.is_remote:
            workers_with_remote.add(wid)

    workers_res = []
    for wid, w_ifaces in worker_ifaces.items():
        cmds = []
        cmds.append(f"ovs-vsctl --may-exist add-br {bridge_name}")
        
        for iface in w_ifaces:
            net = net_map.get(iface.network_id)
            if net:
                if net.vlan_inner == 0:
                    cmds.append(f"ovs-vsctl add-port {bridge_name} {iface.tap_name}")
                else:
                    cmds.append(f"ovs-vsctl add-port {bridge_name} {iface.tap_name} tag={net.vlan_inner}")
        
        if wid in workers_with_remote:
            patch_wk = f"patch-to-wk-{slice_id}"
            patch_sl = f"patch-to-sl-{slice_id}"
            cmds.append(f"ovs-vsctl add-port {bridge_name} {patch_wk} -- set interface {patch_wk} type=patch options:peer={patch_sl}")
            cmds.append(f"ovs-vsctl add-port br-wk {patch_sl} tag={vlan_slice} -- set interface {patch_sl} type=patch options:peer={patch_wk}")
            cmds.append("ovs-vsctl --may-exist add-port br-wk ens4")
            
        workers_res.append(OvsWorkerCommand(worker_id=wid, commands=cmds))

    return OvsCommandResponse(
        slice_id=slice_id,
        vlan_slice=vlan_slice,
        bridge_name=bridge_name,
        workers=workers_res
    )

@router.post("/networking/security/rules", response_model=SecurityRuleResponse, status_code=201)
async def create_rule(rule: SecurityRuleCreate, db: AsyncSession = Depends(get_db)):
    if rule.src_vm_id == rule.dst_vm_id:
        raise HTTPException(status_code=400, detail="src and dst must be different")
    if rule.protocol not in ("tcp", "udp", "icmp", "any"):
        raise HTTPException(status_code=400, detail="Invalid protocol")
    if rule.action not in ("ALLOW", "DENY"):
        raise HTTPException(status_code=400, detail="Invalid action")
    if rule.protocol == "icmp" and (rule.port_min is not None or rule.port_max is not None):
        raise HTTPException(status_code=400, detail="ICMP does not use ports")

    new_rule = SecurityRule(**rule.model_dump())
    db.add(new_rule)
    await db.commit()
    await db.refresh(new_rule)
    return new_rule

@router.get("/networking/security/rules/{slice_id}", response_model=List[SecurityRuleResponse])
async def get_rules(slice_id: int, db: AsyncSession = Depends(get_db)):
    res = await db.execute(select(SecurityRule).where(SecurityRule.slice_id == slice_id))
    return res.scalars().all()

@router.delete("/networking/security/rules/{rule_id}", status_code=204)
async def delete_rule(rule_id: int, db: AsyncSession = Depends(get_db)):
    res = await db.execute(select(SecurityRule).where(SecurityRule.id == rule_id))
    rule = res.scalar_one_or_none()
    if rule:
        await db.delete(rule)
        await db.commit()

@router.get("/networking/security/flows/{slice_id}", response_model=FlowResponse)
async def get_flows(slice_id: int, db: AsyncSession = Depends(get_db)):
    bridge_name = f"br-sl-{slice_id}"
    setup_flows = [
        OvsFlow(bridge=bridge_name, flow="priority=10,arp,actions=normal"),
        OvsFlow(bridge=bridge_name, flow="priority=1,ip,actions=drop")
    ]
    
    rules_res = await db.execute(select(SecurityRule).where(SecurityRule.slice_id == slice_id))
    rules = rules_res.scalars().all()

    nets_res = await db.execute(select(Network).where(Network.slice_id == slice_id))
    net_ids = [n.id for n in nets_res.scalars().all()]

    ifaces_res = await db.execute(select(VmInterface).where(VmInterface.network_id.in_(net_ids)))
    ifaces = ifaces_res.scalars().all()

    iface_map = {}
    for iface in ifaces:
        iface_map.setdefault(iface.vm_id, []).append(iface)

    policy_flows = []
    for rule in rules:
        for src_iface in iface_map.get(rule.src_vm_id, []):
            for dst_iface in iface_map.get(rule.dst_vm_id, []):
                if src_iface.network_id != dst_iface.network_id:
                    continue

                action_str = "normal" if rule.action == "ALLOW" else "drop"
                
                proto = ""
                if rule.protocol == "icmp":
                    proto = "icmp,"
                elif rule.protocol != "any":
                    proto = f"{rule.protocol},"
                else:
                    proto = "ip,"

                port_str = ""
                if rule.protocol in ("tcp", "udp") and rule.port_min is not None:
                    if rule.port_min == rule.port_max or rule.port_max is None:
                        port_str = f"tp_dst={rule.port_min},"
                    else:
                        port_str = f"tp_dst={rule.port_min}/{rule.port_max},"

                flow = f"priority={rule.priority},{proto}in_port={src_iface.tap_name},nw_src={src_iface.ip_address},nw_dst={dst_iface.ip_address},{port_str}actions={action_str}"
                policy_flows.append(OvsFlow(bridge=bridge_name, flow=flow))

    return FlowResponse(slice_id=slice_id, setup_flows=setup_flows, policy_flows=policy_flows)

@router.get("/networking/nat/commands/{slice_id}", response_model=NatCommandResponse)
async def nat_commands(slice_id: int, db: AsyncSession = Depends(get_db)):
    nets_res = await db.execute(select(Network).where(Network.slice_id == slice_id, Network.internet_access == True))
    networks = nets_res.scalars().all()

    bridge_name = f"br-sl-{slice_id}"
    nat_networks = []
    for net in networks:
        cmds = [
            "sysctl -w net.ipv4.ip_forward=1",
            f"iptables -t nat -A POSTROUTING -s {net.subnet_cidr} -o ens4 -j MASQUERADE",
            f"iptables -A FORWARD -i ens4 -o {bridge_name} -m state --state RELATED,ESTABLISHED -j ACCEPT",
            f"iptables -A FORWARD -i {bridge_name} -o ens4 -j ACCEPT"
        ]
        nat_networks.append(NatNetworkCommand(network_id=net.id, subnet_cidr=net.subnet_cidr, commands=cmds))

    return NatCommandResponse(slice_id=slice_id, nat_networks=nat_networks)
