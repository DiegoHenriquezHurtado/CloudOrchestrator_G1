from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select, update, func
from typing import List, Dict, Set
import random

from app.database import get_db
from app.models import VlanPool, Slice, Network, VmInterface, VirtualMachine
from app.schemas import (
    AllocateRequest, AllocateResponse, ReleaseRequest, VlanAvailableResponse,
    SliceNetworkResponse, OvsCommandResponse, OvsWorkerCommand, NetworkDetail, InterfaceDetail
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
        if link.vm_b_id == 0 or link.vm_a_id == 0:
            target_vm_id = link.vm_a_id if link.vm_b_id == 0 else link.vm_b_id
            target_iface = link.iface_a if link.vm_b_id == 0 else link.iface_b
            worker_id = request.placement_map.get(str(target_vm_id))
            if worker_id is None:
                raise HTTPException(status_code=400, detail="Incomplete placement_map for internet link")
            
            mac = generate_mac()
            tap = f"tap-vm{target_vm_id}-{target_iface}"
            iface_obj = VmInterface(
                vm_id=target_vm_id,
                network_id=None,
                mac_address=mac,
                interface_name=target_iface,
                tap_name=tap,
                bridge_name="br-inet"
            )
            db.add(iface_obj)
            networks_response.append(NetworkDetail(
                network_id=None,
                id=None,
                link_name=link.link_name,
                vlan_inner=0,
                is_remote=False,
                interfaces=[
                    InterfaceDetail(vm_id=target_vm_id, interface_name=target_iface, tap_name=tap, mac_address=mac, bridge_name="br-inet", worker_id=worker_id)
                ]
            ))
            continue

        worker_a = request.placement_map.get(str(link.vm_a_id))
        worker_b = request.placement_map.get(str(link.vm_b_id))
        
        if worker_a is None or worker_b is None:
            raise HTTPException(status_code=400, detail="Incomplete placement_map")

        is_remote = (worker_a != worker_b)
        vlan_inner = current_vlan_inner
        current_vlan_inner += 100
        
        net = Network(
            slice_id=request.slice_id,
            vlan_inner=vlan_inner,
            is_remote=is_remote
        )
        db.add(net)
        await db.flush()

        mac_a = generate_mac()
        tap_a = f"tap-vm{link.vm_a_id}-{link.iface_a}"
        
        iface_a = VmInterface(
            vm_id=link.vm_a_id,
            network_id=net.id,
            mac_address=mac_a,
            interface_name=link.iface_a,
            tap_name=tap_a,
            bridge_name=bridge_name
        )
        db.add(iface_a)

        mac_b = generate_mac()
        tap_b = f"tap-vm{link.vm_b_id}-{link.iface_b}"
        
        iface_b = VmInterface(
            vm_id=link.vm_b_id,
            network_id=net.id,
            mac_address=mac_b,
            interface_name=link.iface_b,
            tap_name=tap_b,
            bridge_name=bridge_name
        )
        db.add(iface_b)

        networks_response.append(NetworkDetail(
            network_id=net.id,
            id=net.id,
            link_name=link.link_name,
            vlan_inner=vlan_inner,
            is_remote=is_remote,
            interfaces=[
                InterfaceDetail(vm_id=link.vm_a_id, interface_name=link.iface_a, tap_name=tap_a, mac_address=mac_a, bridge_name=bridge_name, worker_id=worker_a),
                InterfaceDetail(vm_id=link.vm_b_id, interface_name=link.iface_b, tap_name=tap_b, mac_address=mac_b, bridge_name=bridge_name, worker_id=worker_b)
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
                interface_name=iface.interface_name,
                tap_name=iface.tap_name,
                bridge_name=iface.bridge_name or f"br-sl-{slice_id}"
            ))
            
        network_details.append(NetworkDetail(
            id=net.id,
            vlan_inner=net.vlan_inner,
            is_remote=net.is_remote,
            interfaces=interfaces
        ))

    if vms:
        inet_res = await db.execute(select(VmInterface).where(VmInterface.network_id.is_(None), VmInterface.vm_id.in_(vms.keys())))
        inet_ifaces = inet_res.scalars().all()
        if inet_ifaces:
            inet_interfaces = []
            for iface in inet_ifaces:
                inet_interfaces.append(InterfaceDetail(
                    vm_id=iface.vm_id,
                    worker_id=vms.get(iface.vm_id),
                    mac_address=iface.mac_address,
                    interface_name=iface.interface_name,
                    tap_name=iface.tap_name,
                    bridge_name=iface.bridge_name or "br-inet"
                ))
            network_details.append(NetworkDetail(
                id=None,
                vlan_inner=0,
                is_remote=False,
                interfaces=inet_interfaces
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

