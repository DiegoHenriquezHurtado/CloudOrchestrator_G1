import random
from fastapi import FastAPI, Depends, HTTPException
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select, update
from typing import List, Dict, Optional, Set

from database import get_db
from models import VlanPool, Network, VmInterface, SecurityRule
from schemas import (
    AllocateRequest, ReleaseRequest,
    NetworkDetail, SliceNetworkResponse,
    OvsWorkerCommands, SliceOvsResponse,
    SecurityRuleCreate, SecurityRuleResponse,
    OvsFlow, SliceFlowsResponse,
    NatCommand, SliceNatResponse,
)

app = FastAPI(title="Networking & Security Module")


def generate_mac() -> str:
    mac = [0x52, 0x54, 0x00,
           random.randint(0x00, 0x7f),
           random.randint(0x00, 0xff),
           random.randint(0x00, 0xff)]
    return ':'.join(f"{b:02x}" for b in mac)


# -------------------------  ALLOCATE -----------------------------------------------------

@app.post("/networking/allocate")
async def allocate_network(request: AllocateRequest, db: AsyncSession = Depends(get_db)):
    """
    Planifica la red de un slice siguiendo el modelo Br-Slice / Vlan-Inner / Vlan-Slice:
      - Reserva UNA sola Vlan-Slice del pool global para todo el slice.
      - Asigna una Vlan-Inner local por enlace (100, 200, 300...).
      - Clasifica cada enlace como local (misma worker) o remoto (workers distintos).
      - El bridge del slice es siempre br-sl-{slice_id}.
    """
    if not request.networks:
        return {"status": "success", "slice_id": request.slice_id,
                "vlan_slice": None, "bridge_name": None,
                "plan": {"networks": [], "vms": []}}

    # 1. Reservar UNA Vlan-Slice del pool para todo el slice
    result = await db.execute(
        select(VlanPool).where(VlanPool.status == 'AVAILABLE').limit(1)
    )
    vlan_row = result.scalars().first()
    if not vlan_row:
        raise HTTPException(status_code=400, detail="No VLANs available in pool")
    vlan_row.status = 'USED'
    db.add(vlan_row)
    vlan_slice: int = vlan_row.vlan_id

    # 2. Mapa worker_id por VM (recibido del Placement)
    vm_worker: Dict[int, int] = {vm.vm_id: vm.worker_id for vm in request.vms}

    bridge_name = f"br-sl-{request.slice_id}"

    # 3. Crear registros de red con Vlan-Inner local y clasificación local/remoto
    network_map: Dict[str, dict] = {}
    network_responses = []

    for i, net_req in enumerate(request.networks):
        vlan_inner = (i + 1) * 100  # 100, 200, 300, ... local al Br-Slice

        # Determinar workers de las VMs en este enlace
        workers_on_link: Set[int] = set()
        for vm in request.vms:
            for iface in vm.interfaces:
                if iface.network_name == net_req.name:
                    workers_on_link.add(vm_worker[vm.vm_id])

        is_remote = len(workers_on_link) > 1

        # Subnet para IPAM: 10.{vlan_slice % 256}.{link_index + 1}.0/24
        subnet = f"10.{vlan_slice % 256}.{i + 1}.0/24"
        subnet_base = f"10.{vlan_slice % 256}.{i + 1}"

        new_net = Network(
            slice_id=request.slice_id,
            vlan_slice=vlan_slice,
            vlan_inner=vlan_inner,
            subnet_cidr=subnet,
            bridge_name=bridge_name,
            is_remote=is_remote,
            internet_access=net_req.internet_access,
        )
        db.add(new_net)
        await db.flush()

        network_map[net_req.name] = {
            "id": new_net.id,
            "vlan_inner": vlan_inner,
            "is_remote": is_remote,
            "subnet_base": subnet_base,
        }
        network_responses.append({
            "name": net_req.name,
            "vlan_slice": vlan_slice,
            "vlan_inner": vlan_inner,
            "subnet_cidr": subnet,
            "bridge_name": bridge_name,
            "is_remote": is_remote,
            "internet_access": net_req.internet_access,
        })

    # 4. Crear interfaces de VM con IPs y TAPs
    vm_responses = []
    ip_counters: Dict[str, int] = {n: 10 for n in network_map}

    for vm in request.vms:
        ifaces_resp = []
        for iface in vm.interfaces:
            net_info = network_map.get(iface.network_name)
            if not net_info:
                raise HTTPException(
                    status_code=400,
                    detail=f"Network '{iface.network_name}' not defined in request"
                )

            ip_addr = f"{net_info['subnet_base']}.{ip_counters[iface.network_name]}"
            ip_counters[iface.network_name] += 1
            mac_addr = generate_mac()
            tap_name = f"tap-{vm.vm_id}-{iface.interface_name}"

            new_iface = VmInterface(
                vm_id=vm.vm_id,
                network_id=net_info['id'],
                worker_id=vm.worker_id,
                mac_address=mac_addr,
                ip_address=ip_addr,
                interface_name=iface.interface_name,
                tap_name=tap_name,
            )
            db.add(new_iface)
            ifaces_resp.append({
                "interface_name": iface.interface_name,
                "mac_address": mac_addr,
                "ip_address": ip_addr,
                "tap_name": tap_name,
                "vlan_inner": net_info["vlan_inner"],
                "is_remote": net_info["is_remote"],
                "bridge_name": bridge_name,
            })
        vm_responses.append({
            "vm_id": vm.vm_id,
            "worker_id": vm.worker_id,
            "interfaces": ifaces_resp,
        })

    await db.commit()

    return {
        "status": "success",
        "slice_id": request.slice_id,
        "vlan_slice": vlan_slice,
        "bridge_name": bridge_name,
        "plan": {"networks": network_responses, "vms": vm_responses},
    }


# ------------------------- RELEASE --------------------------------------------------------

@app.post("/networking/release")
async def release_network(request: ReleaseRequest, db: AsyncSession = Depends(get_db)):
    result = await db.execute(select(Network).where(Network.slice_id == request.slice_id))
    networks = result.scalars().all()

    # Un solo vlan_slice por slice — deduplicar por si acaso
    vlan_slices = list({net.vlan_slice for net in networks if net.vlan_slice})

    if vlan_slices:
        await db.execute(
            update(VlanPool)
            .where(VlanPool.vlan_id.in_(vlan_slices))
            .values(status='AVAILABLE')
        )

    for net in networks:
        await db.delete(net)

    await db.commit()
    return {"status": "success",
            "message": f"Released {len(vlan_slices)} VLAN(s) for slice {request.slice_id}"}


# ---------------------------- CONSULTAS ---------------------------------------------

@app.get("/networking/vlans/available")
async def get_available_vlans(db: AsyncSession = Depends(get_db)):
    result = await db.execute(select(VlanPool).where(VlanPool.status == 'AVAILABLE'))
    vlans = result.scalars().all()
    return {"available": len(vlans)}


@app.get("/networking/networks/{slice_id}", response_model=SliceNetworkResponse)
async def get_slice_networks(slice_id: int, db: AsyncSession = Depends(get_db)):
    nets_result = await db.execute(select(Network).where(Network.slice_id == slice_id))
    networks = nets_result.scalars().all()

    if not networks:
        raise HTTPException(status_code=404, detail=f"No networks found for slice {slice_id}")

    vlan_slice = networks[0].vlan_slice
    bridge_name = networks[0].bridge_name

    network_details = []
    for net in networks:
        ifaces_result = await db.execute(
            select(VmInterface).where(VmInterface.network_id == net.id)
        )
        ifaces = ifaces_result.scalars().all()
        network_details.append(NetworkDetail(
            id=net.id,
            vlan_slice=net.vlan_slice,
            vlan_inner=net.vlan_inner,
            subnet_cidr=net.subnet_cidr,
            bridge_name=net.bridge_name,
            is_remote=net.is_remote or False,
            internet_access=net.internet_access or False,
            interfaces=[
                {
                    "vm_id": iface.vm_id,
                    "worker_id": iface.worker_id,
                    "mac_address": iface.mac_address,
                    "ip_address": iface.ip_address,
                    "interface_name": iface.interface_name,
                    "tap_name": iface.tap_name,
                }
                for iface in ifaces
            ]
        ))

    return SliceNetworkResponse(
        slice_id=slice_id,
        vlan_slice=vlan_slice,
        bridge_name=bridge_name,
        networks=network_details,
    )


# --------------- GENERADOR DE COMANDOS OVS -----------------------------------------------

@app.get("/networking/ovs/commands/{slice_id}", response_model=SliceOvsResponse)
async def get_ovs_commands(slice_id: int, db: AsyncSession = Depends(get_db)):
    """
    Genera los comandos ovs-vsctl que el Driver debe ejecutar en cada Worker
    para construir la topología:
      - Crea br-sl-{slice_id} en cada Worker que tenga VMs del slice.
      - Conecta cada TAP al Br-Slice con su Vlan-Inner.
      - Para enlaces remotos: crea Patch Ports al Br-WK con tag=Vlan-Slice.
      - Asegura que br-wk tenga ens4 como trunk (idempotente).
    """
    nets_result = await db.execute(select(Network).where(Network.slice_id == slice_id))
    networks = nets_result.scalars().all()
    if not networks:
        raise HTTPException(status_code=404, detail=f"No networks for slice {slice_id}")

    vlan_slice = networks[0].vlan_slice
    bridge_name = networks[0].bridge_name  # br-sl-{slice_id}

    net_ids = [n.id for n in networks]
    ifaces_result = await db.execute(
        select(VmInterface).where(VmInterface.network_id.in_(net_ids))
    )
    all_ifaces = ifaces_result.scalars().all()

    # Vlan-Inner por network_id
    vlan_inner_by_net: Dict[int, int] = {n.id: n.vlan_inner for n in networks}
    # ¿El enlace es remoto?
    is_remote_by_net: Dict[int, bool] = {n.id: n.is_remote for n in networks}

    # Agrupar interfaces por worker
    ifaces_by_worker: Dict[int, List] = {}
    for iface in all_ifaces:
        wid = iface.worker_id or 0
        ifaces_by_worker.setdefault(wid, []).append(iface)

    # Determinar qué workers tienen al menos un enlace remoto
    workers_with_remote: Set[int] = set()
    for iface in all_ifaces:
        if is_remote_by_net.get(iface.network_id):
            workers_with_remote.add(iface.worker_id or 0)

    worker_commands: List[OvsWorkerCommands] = []

    for worker_id, ifaces in sorted(ifaces_by_worker.items()):
        cmds: List[str] = []

        # 1. Crear Br-Slice (idempotente)
        cmds.append(f"ovs-vsctl --may-exist add-br {bridge_name}")

        # 2. Conectar cada TAP al Br-Slice con su Vlan-Inner
        for iface in ifaces:
            vlan_inner = vlan_inner_by_net[iface.network_id]
            if vlan_inner == 0:
                # Enlace local untagged (acceso sin etiqueta)
                cmds.append(
                    f"ovs-vsctl add-port {bridge_name} {iface.tap_name}"
                )
            else:
                cmds.append(
                    f"ovs-vsctl add-port {bridge_name} {iface.tap_name}"
                    f" tag={vlan_inner}"
                )

        # 3. Para enlaces remotos: Patch Port Br-Slice ↔ Br-WK
        if worker_id in workers_with_remote:
            patch_sl = f"patch-to-wk-{slice_id}"
            patch_wk = f"patch-to-sl-{slice_id}"

            # Patch del Br-Slice hacia el Br-WK
            cmds.append(
                f"ovs-vsctl add-port {bridge_name} {patch_sl}"
                f" -- set interface {patch_sl} type=patch"
                f" options:peer={patch_wk}"
            )
            # Patch del Br-WK hacia el Br-Slice (tag=Vlan-Slice = encapsulación inter-worker)
            cmds.append(
                f"ovs-vsctl add-port br-wk {patch_wk}"
                f" tag={vlan_slice}"
                f" -- set interface {patch_wk} type=patch"
                f" options:peer={patch_sl}"
            )
            # Asegurar que ens4 esté en br-wk como trunk (idempotente)
            cmds.append("ovs-vsctl --may-exist add-port br-wk ens4")

        worker_commands.append(OvsWorkerCommands(worker_id=worker_id, commands=cmds))

    return SliceOvsResponse(
        slice_id=slice_id,
        vlan_slice=vlan_slice,
        bridge_name=bridge_name,
        workers=worker_commands,
    )


# -------------------- SECURITY RULES ---------------------------------------------------------

@app.post("/networking/security/rules", response_model=SecurityRuleResponse, status_code=201)
async def create_security_rule(rule: SecurityRuleCreate, db: AsyncSession = Depends(get_db)):
    if rule.src_vm_id == rule.dst_vm_id:
        raise HTTPException(status_code=400, detail="src_vm_id and dst_vm_id must be different")
    if rule.protocol not in ("tcp", "udp", "icmp", "any"):
        raise HTTPException(status_code=400, detail="protocol must be tcp, udp, icmp, or any")
    if rule.action not in ("ALLOW", "DENY"):
        raise HTTPException(status_code=400, detail="action must be ALLOW or DENY")
    if rule.protocol == "icmp" and (rule.port_min is not None or rule.port_max is not None):
        raise HTTPException(status_code=400, detail="ICMP does not use ports")

    new_rule = SecurityRule(
        slice_id=rule.slice_id,
        src_vm_id=rule.src_vm_id,
        dst_vm_id=rule.dst_vm_id,
        protocol=rule.protocol,
        port_min=rule.port_min,
        port_max=rule.port_max,
        action=rule.action,
        priority=rule.priority,
    )
    db.add(new_rule)
    await db.commit()
    await db.refresh(new_rule)
    return new_rule


@app.get("/networking/security/rules/{slice_id}", response_model=List[SecurityRuleResponse])
async def get_security_rules(slice_id: int, db: AsyncSession = Depends(get_db)):
    result = await db.execute(select(SecurityRule).where(SecurityRule.slice_id == slice_id))
    return result.scalars().all()


@app.delete("/networking/security/rules/{rule_id}", status_code=204)
async def delete_security_rule(rule_id: int, db: AsyncSession = Depends(get_db)):
    result = await db.execute(select(SecurityRule).where(SecurityRule.id == rule_id))
    rule = result.scalars().first()
    if not rule:
        raise HTTPException(status_code=404, detail="Rule not found")
    await db.delete(rule)
    await db.commit()


# ------- OpenFlow generator (seguridad intra-Br-Slice) ----------------------------------------

def _build_flow(priority: int, bridge: str, src_ip: str, dst_ip: str,
                src_tap: str, protocol: str,
                port_min: Optional[int], port_max: Optional[int],
                action: str) -> OvsFlow:
    ovs_action = "normal" if action == "ALLOW" else "drop"

    if protocol == "any":
        proto_match, port_match = "ip", ""
    elif protocol == "icmp":
        proto_match, port_match = "icmp", ""
    else:
        proto_match = protocol
        if port_min is not None and port_max is not None:
            port_match = f",tp_dst={port_min}" if port_min == port_max else f",tp_dst={port_min}/{port_max}"
        elif port_min is not None:
            port_match = f",tp_dst={port_min}"
        else:
            port_match = ""

    flow = (
        f"priority={priority},{proto_match},"
        f"in_port={src_tap},"
        f"nw_src={src_ip},nw_dst={dst_ip}"
        f"{port_match},"
        f"actions={ovs_action}"
    )
    return OvsFlow(bridge=bridge, flow=flow)


@app.get("/networking/security/flows/{slice_id}", response_model=SliceFlowsResponse)
async def get_security_flows(slice_id: int, db: AsyncSession = Depends(get_db)):
    """
    Genera reglas OpenFlow para el Br-Slice del slice.
    El tráfico VM↔VM dentro del Br-Slice no pasa por el kernel del host,
    por lo que iptables no aplica — el enforcement es con ovs-ofctl.
    """
    nets_result = await db.execute(select(Network).where(Network.slice_id == slice_id))
    networks = nets_result.scalars().all()
    if not networks:
        raise HTTPException(status_code=404, detail=f"No networks for slice {slice_id}")

    bridge_name = networks[0].bridge_name  # br-sl-{slice_id}

    rules_result = await db.execute(select(SecurityRule).where(SecurityRule.slice_id == slice_id))
    rules = rules_result.scalars().all()

    ifaces_result = await db.execute(
        select(VmInterface).where(VmInterface.network_id.in_([n.id for n in networks]))
    )
    all_ifaces = ifaces_result.scalars().all()

    # vm_id : lista de {network_id, ip_address, tap_name}
    iface_map: Dict[int, List[dict]] = {}
    for iface in all_ifaces:
        iface_map.setdefault(iface.vm_id, []).append({
            "network_id": iface.network_id,
            "ip_address": iface.ip_address,
            "tap_name": iface.tap_name,
        })

    # Setup: ARP allow + default-deny (una sola vez por bridge)
    setup_flows = [
        OvsFlow(bridge=bridge_name, flow="priority=10,arp,actions=normal"),
        OvsFlow(bridge=bridge_name, flow="priority=1,ip,actions=drop"),
    ]

    policy_flows: List[OvsFlow] = []
    for rule in rules:
        for src in iface_map.get(rule.src_vm_id, []):
            for dst in iface_map.get(rule.dst_vm_id, []):
                if src["network_id"] != dst["network_id"]:
                    continue
                policy_flows.append(_build_flow(
                    priority=rule.priority,
                    bridge=bridge_name,
                    src_ip=src["ip_address"],
                    dst_ip=dst["ip_address"],
                    src_tap=src["tap_name"],
                    protocol=rule.protocol,
                    port_min=rule.port_min,
                    port_max=rule.port_max,
                    action=rule.action,
                ))

    return SliceFlowsResponse(
        slice_id=slice_id,
        setup_flows=setup_flows,
        policy_flows=policy_flows,
    )


# --------------- NAT / Internet Access --------------------------------------------

@app.get("/networking/nat/commands/{slice_id}", response_model=SliceNatResponse)
async def get_nat_commands(slice_id: int, db: AsyncSession = Depends(get_db)):
    """
    Genera comandos iptables para NAT en redes con internet_access=True.
    El tráfico VM - Internet SÍ pasa por el kernel del Worker (iptables MASQUERADE),
    a diferencia del tráfico intra-Br-Slice que OvS maneja sin kernel.
    """
    nets_result = await db.execute(
        select(Network).where(
            Network.slice_id == slice_id,
            Network.internet_access == True,
        )
    )
    nat_networks = nets_result.scalars().all()

    if not nat_networks:
        return SliceNatResponse(slice_id=slice_id, nat_networks=[])

    result = []
    for net in nat_networks:
        result.append(NatCommand(
            network_id=net.id,
            subnet_cidr=net.subnet_cidr,
            commands=[
                "sysctl -w net.ipv4.ip_forward=1",
                f"iptables -t nat -A POSTROUTING -s {net.subnet_cidr} -o ens4 -j MASQUERADE",
                f"iptables -A FORWARD -i ens4 -o {net.bridge_name} -m state --state RELATED,ESTABLISHED -j ACCEPT",
                f"iptables -A FORWARD -i {net.bridge_name} -o ens4 -j ACCEPT",
            ]
        ))

    return SliceNatResponse(slice_id=slice_id, nat_networks=result)
