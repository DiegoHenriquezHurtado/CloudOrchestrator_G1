"""
Driver Service — Capa de ejecución en Workers (Puerto 8088)

Único módulo que toca el hardware/kernel de los Workers.
Genera y ejecuta comandos SSH para:
  - Thin Provisioning (qemu-img)
  - Bridges OVS (ovs-vsctl)
  - TAPs y Patch Ports
  - Lanzamiento QEMU (-pidfile, -vnc)
  - Reglas OpenFlow (ovs-ofctl)
  - NAT/iptables

Reglas duras:
  - NUNCA tocar ens3 (Management)
  - NUNCA borrar br-wk ni ens4
  - Siempre usar -pidfile /tmp/{vm_name}.pid
  - Siempre usar backing files (Thin Provisioning)
"""

import os
import logging
from typing import List, Dict, Optional

import httpx
from schemas import ExecuteRequest, ExecuteSuccessResponse, ExecuteFailureResponse
from ssh_client import execute_on_worker, CommandResult

logger = logging.getLogger("driver")

NETWORKING_URL = os.getenv("NETWORKING_URL", "http://networking:8085")


class DriverService:

    async def execute(self, request: ExecuteRequest):
        """Punto de entrada principal. Despacha según task_type."""
        if request.task_type == "CREATE_VM":
            return await self._create_vm(request)
        elif request.task_type == "DELETE_VM":
            return await self._delete_vm(request)
        elif request.task_type == "APPLY_SECURITY":
            return await self._apply_security(request)
        else:
            return ExecuteFailureResponse(
                task_id=request.task_id,
                status="FAILED",
                error_msg=f"Unknown task_type: {request.task_type}",
            )

    # ==================================================================
    # CREATE_VM
    # ==================================================================
    async def _create_vm(self, req: ExecuteRequest):
        commands = []
        rollback_actions = []

        # --- 1. Thin Provisioning ---
        base_path = f"/mnt/storage/base/{req.vm.base_image}"
        commands.append(f"sudo qemu-img create -f qcow2 -b {base_path} -F qcow2 {req.vm.instance_path}")
        rollback_actions.append(f"sudo rm -f {req.vm.instance_path}")

        # --- 2. Bridges idempotentes ---
        commands.append("sudo ovs-vsctl --may-exist add-br br-wk")
        commands.append("sudo ovs-vsctl --may-exist add-port br-wk ens4")

        bridge_name = f"br-sl-{req.slice.id}"
        if req.interfaces:
            bridge_name = req.interfaces[0].bridge_name
        commands.append(f"sudo ovs-vsctl --may-exist add-br {bridge_name}")

        # --- 3. TAPs con Vlan-Inner ---
        has_remote = False
        for iface in req.interfaces:
            # Pre-crear el TAP para que OVS no falle al intentar agregarlo si no existe
            commands.append(f"sudo ip tuntap add mode tap {iface.tap_name} 2>/dev/null || true")
            commands.append(f"sudo ip link set {iface.tap_name} up")
            
            if iface.vlan_inner and iface.vlan_inner > 0:
                commands.append(f"sudo ovs-vsctl --may-exist add-port {bridge_name} {iface.tap_name} tag={iface.vlan_inner}")
            else:
                commands.append(f"sudo ovs-vsctl --may-exist add-port {bridge_name} {iface.tap_name}")
            rollback_actions.append(f"sudo ovs-vsctl --if-exists del-port {bridge_name} {iface.tap_name}")
            if iface.is_remote:
                has_remote = True

        # --- 4. Patch Ports + QinQ (solo si hay enlaces remotos) ---
        # Modelo del ejemplo QinQ:
        #   br-sl-1 (inferior) ←patch→ br-wk (superior) ←ens4→ transporte
        #   patch-to-wk-1: vlan_mode=dot1q, trunks={vlan_inners}
        #   patch-to-sl-1: vlan_mode=dot1q, trunks={vlan_inners}
        #   ens4:           vlan_mode=dot1q-tunnel, tag={vlan_slice}
        if has_remote and req.slice.vlan_slice:
            veth_wk = f"veth-wk-{req.slice.id}"
            veth_sl = f"veth-sl-{req.slice.id}"

            # Crear veth pair
            commands.append(f"sudo ip link add {veth_sl} type veth peer name {veth_wk} 2>/dev/null || true")
            commands.append(f"sudo ip link set {veth_sl} up")
            commands.append(f"sudo ip link set {veth_wk} up")
            
            # Lado br-sl-1: Trunk normal
            commands.append(
                f"sudo ovs-vsctl --may-exist add-port {bridge_name} {veth_sl} "
                f"-- set port {veth_sl} vlan_mode=trunk"
            )
            
            # Lado br-wk: Customer-Facing port (pushea el S-Tag)
            commands.append(
                f"sudo ovs-vsctl --may-exist add-port br-wk {veth_wk} "
                f"-- set port {veth_wk} vlan_mode=dot1q-tunnel tag={req.slice.vlan_slice} other_config:qinq-ethtype=802.1q"
            )

            # ens4: Trunk normal (transporta el S-Tag hacia la red física)
            commands.append(
                f"sudo ovs-vsctl set port ens4 vlan_mode=trunk"
            )

        # --- 4.5. Generar Cloud-Init dinámico (Ubuntu/Debian) ---
        # Se genera en NFS, añadiendo tiempos de espera para mitigar latencias de sincronizacion
        seed_path = f"/mnt/storage/instances/{req.vm.name}-seed.iso"
        
        # 1. user-data (Hostname, Passwords y SSH)
        commands.append(
            f"cat << 'EOF' > /tmp/user-data-{req.vm.name}\n"
            f"#cloud-config\n"
            f"hostname: {req.vm.name}\n"
            f"manage_etc_hosts: true\n"
            f"chpasswd:\n"
            f"  list: |\n"
            f"    root:root\n"
            f"    ubuntu:ubuntu\n"
            f"    debian:debian\n"
            f"  expire: False\n"
            f"ssh_pwauth: True\n"
            f"EOF"
        )
        
        # 2. meta-data (Hostnames)
        commands.append(f"echo -e 'instance-id: {req.vm.name}\\nlocal-hostname: {req.vm.name}' > /tmp/meta-data-{req.vm.name}")
        
        # 3. network-config (Version 1 - Universal por MAC Address)
        # Ubuntu lo traduce a Netplan, Debian lo traduce a ENI + Udev Rules
        sorted_ifaces = sorted(req.interfaces, key=lambda x: x.interface_name)
        net_cfg = ["version: 1", "config:"]
        for iface in sorted_ifaces:
            net_cfg.extend([
                f"  - type: physical",
                f"    name: {iface.interface_name}",
                f"    mac_address: '{iface.mac_address}'",
                f"    subnets:",
                f"      - type: static",
                f"        address: {iface.ip_address}",
                f"        netmask: 255.255.255.0"
            ])
        net_cfg_content = "\\n".join(net_cfg)
        commands.append(f"echo -e '{net_cfg_content}' > /tmp/network-config-{req.vm.name}")
        
        # 4. Generar ISO usando cloud-localds (y agregar sleep para compensar la latencia del NFS)
        commands.append(
            f"sudo cloud-localds --network-config=/tmp/network-config-{req.vm.name} {seed_path} /tmp/user-data-{req.vm.name} /tmp/meta-data-{req.vm.name}; "
            f"sync; sleep 2"
        )
        
        # 5. Limpiar archivos temporales
        commands.append(f"sudo rm -f /tmp/user-data-{req.vm.name} /tmp/meta-data-{req.vm.name} /tmp/network-config-{req.vm.name}")

        # --- 5. Lanzar QEMU ---
        vnc_display = req.vm.id
        vnc_port = 5900 + vnc_display

        qemu_parts = [
            f"SEED_OPT=\"\"; if [ -f {seed_path} ]; then SEED_OPT=\"-cdrom {seed_path}\"; elif [ -f /mnt/storage/base/seed.iso ]; then SEED_OPT=\"-cdrom /mnt/storage/base/seed.iso\"; fi; "
            "sudo qemu-system-x86_64 $SEED_OPT",
            "-enable-kvm",
            f"-m {req.vm.ram}",
            f"-smp {req.vm.vcpu}",
            f"{req.vm.instance_path}",
        ]

        for i, iface in enumerate(sorted_ifaces):
            qemu_parts.append(f"-netdev tap,id=net{i},ifname={iface.tap_name},script=no,downscript=no")
            qemu_parts.append(f"-device virtio-net-pci,netdev=net{i},mac={iface.mac_address}")

        qemu_parts.extend([
            f"-pidfile /tmp/{req.vm.name}.pid",
            f"-vnc :{vnc_display}",
            "-daemonize",
        ])

        qemu_cmd = " \\\n  ".join(qemu_parts)
        commands.append(qemu_cmd)

        # --- 6. Levantar TAPs ---
        for iface in sorted_ifaces:
            commands.append(f"sudo ip link set {iface.tap_name} up")

        # --- 7. Leer PID ---
        commands.append(f"sudo cat /tmp/{req.vm.name}.pid")

        # --- Ejecutar ---
        results = await execute_on_worker(req.worker_ip, commands)

        failed_result = next((r for r in results if not r.success), None)
        if failed_result:
            rb_results = await self._rollback(req.worker_ip, rollback_actions)
            return ExecuteFailureResponse(
                task_id=req.task_id,
                status="FAILED",
                error_msg=f"Command failed: {failed_result.command[:100]} — {failed_result.stderr[:200]}",
                rollback_actions=[f"Executed: {r.command}" for r in rb_results],
            )

        pid_result = results[-1]
        process_id = int(pid_result.stdout.strip()) if pid_result.stdout.strip().isdigit() else None

        return ExecuteSuccessResponse(
            task_id=req.task_id,
            status="READY",
            process_id=process_id,
            vnc_port=vnc_port,
            commands_executed=[r.command for r in results],
        )

    # ==================================================================
    # DELETE_VM
    # ==================================================================
    async def _delete_vm(self, req: ExecuteRequest):
        commands = []

        # 1. Kill QEMU
        if req.process_id:
            commands.append(f"sudo kill {req.process_id} 2>/dev/null || true")

        # 2. Remove instance disk
        commands.append(f"sudo rm -f {req.vm.instance_path}")

        # 3. Remove pidfile
        commands.append(f"sudo rm -f /tmp/{req.vm.name}.pid")

        # 4. Delete TAPs
        bridge_name = f"br-sl-{req.slice.id}"
        if req.interfaces:
            bridge_name = req.interfaces[0].bridge_name

        for iface in req.interfaces:
            commands.append(f"sudo ovs-vsctl --if-exists del-port {bridge_name} {iface.tap_name}")

        # 3.5. Remove dynamically generated seed.iso from NFS if exists
        commands.append(f"sudo rm -f /mnt/storage/instances/{req.vm.name}-seed.iso")

        # 5 y 6. Delete veth-ports and bridge ONLY if it's the last VM of the slice
        veth_wk = f"veth-wk-{req.slice.id}"
        veth_sl = f"veth-sl-{req.slice.id}"
        commands.append(
            f"tap_count=$(sudo ovs-vsctl list-ports {bridge_name} 2>/dev/null | grep -c '^tap-' || true); "
            f"if [ \"$tap_count\" -eq 0 ]; then "
            f"sudo ovs-vsctl --if-exists del-port {bridge_name} {veth_sl}; "
            f"sudo ovs-vsctl --if-exists del-port br-wk {veth_wk}; "
            f"sudo ip link del {veth_sl} 2>/dev/null || true; "
            f"sudo ovs-vsctl --if-exists del-br {bridge_name}; "
            f"fi"
        )

        results = await execute_on_worker(req.worker_ip, commands)

        failed = next((r for r in results if not r.success), None)
        if failed:
            return ExecuteFailureResponse(
                task_id=req.task_id,
                status="FAILED",
                error_msg=f"Cleanup failed: {failed.command[:100]} — {failed.stderr[:200]}",
            )

        return ExecuteSuccessResponse(
            task_id=req.task_id,
            status="READY",
            commands_executed=[r.command for r in results],
        )

    # ==================================================================
    # APPLY_SECURITY
    # ==================================================================
    async def _apply_security(self, req: ExecuteRequest):
        commands = []
        bridge_name = f"br-sl-{req.slice.id}"

        # 1. Setup flows (ARP allow + default-deny IP)
        for flow_entry in (req.setup_flows or []):
            bridge = flow_entry.get("bridge", bridge_name)
            flow = flow_entry.get("flow", "")
            if flow:
                commands.append(f'sudo ovs-ofctl add-flow {bridge} "{flow}"')

        # 2. Policy flows (user rules from security_rules)
        for flow_entry in (req.policy_flows or []):
            bridge = flow_entry.get("bridge", bridge_name)
            flow = flow_entry.get("flow", "")
            if flow:
                commands.append(f'sudo ovs-ofctl add-flow {bridge} "{flow}"')

        # 3. NAT commands for networks with internet_access
        nat_commands = await self._fetch_nat_commands(req.slice.id)
        commands.extend(nat_commands)

        results = await execute_on_worker(req.worker_ip, commands)

        failed = next((r for r in results if not r.success), None)
        if failed:
            return ExecuteFailureResponse(
                task_id=req.task_id,
                status="FAILED",
                error_msg=f"Security failed: {failed.command[:100]} — {failed.stderr[:200]}",
            )

        return ExecuteSuccessResponse(
            task_id=req.task_id,
            status="READY",
            commands_executed=[r.command for r in results],
        )

    # ==================================================================
    # Helpers
    # ==================================================================
    async def _rollback(self, worker_ip: str, actions: List[str]) -> List[CommandResult]:
        """Ejecuta acciones de rollback en orden inverso. Best-effort."""
        if not actions:
            return []
        logger.warning(f"Executing rollback ({len(actions)} actions) on {worker_ip}")
        results = await execute_on_worker(worker_ip, list(reversed(actions)))
        return results

    async def _fetch_nat_commands(self, slice_id: int) -> List[str]:
        """Consulta GET /networking/nat/commands/{slice_id} para comandos iptables."""
        try:
            async with httpx.AsyncClient(timeout=10.0) as client:
                res = await client.get(f"{NETWORKING_URL}/networking/nat/commands/{slice_id}")
                if res.status_code == 200:
                    data = res.json()
                    commands = []
                    for net in data.get("nat_networks", []):
                        commands.extend(net.get("commands", []))
                    return commands
        except httpx.RequestError as e:
            logger.warning(f"NAT commands fetch failed: {e}")
        return []
