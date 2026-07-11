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
        if req.vm.disk > 0:
            commands.append(f"sudo qemu-img resize {req.vm.instance_path} {req.vm.disk}G")
        rollback_actions.append(f"sudo rm -f {req.vm.instance_path}")

        # --- 1.5. Cloud-Init Ligero (Credenciales y Hostname sin red) ---
        seed_path = f"/mnt/storage/instances/{req.vm.name}-seed.iso"
        user_data_path = f"/tmp/user-data-{req.vm.name}"
        meta_data_path = f"/tmp/meta-data-{req.vm.name}"

        user_data_content = f"""#cloud-config
hostname: {req.vm.name}
manage_etc_hosts: true
users:
  - default
  - name: cloudg1
    gecos: Cloud G1 User
    sudo: ALL=(ALL) NOPASSWD:ALL
    groups: [sudo, users]
    lock_passwd: false
chpasswd:
  list: |
    root:root
    cloudg1:cloudg1
    debian:debian
    ubuntu:ubuntu
  expire: False
ssh_pwauth: True
"""
        meta_data_content = f"""instance-id: {req.vm.name}-{req.vm.id}
local-hostname: {req.vm.name}
"""
        commands.append(f"cat << 'EOF' > {user_data_path}\n{user_data_content}EOF")
        commands.append(f"cat << 'EOF' > {meta_data_path}\n{meta_data_content}EOF")
        commands.append(f"sudo cloud-localds {seed_path} {user_data_path} {meta_data_path}; sync; sleep 10")
        commands.append(f"sudo rm -f {user_data_path} {meta_data_path}")
        rollback_actions.append(f"sudo rm -f {seed_path} {user_data_path} {meta_data_path}")

        # --- 2. Bridges idempotentes ---
        commands.append("sudo ovs-vsctl --may-exist add-br br-wk")
        commands.append("sudo ovs-vsctl --may-exist add-port br-wk ens4")

        # Configuración NAT / Internet Plug & Play en Worker
        commands.append("sudo ovs-vsctl --may-exist add-br br-inet")
        commands.append("sudo ip addr add 172.16.0.1/24 dev br-inet 2>/dev/null || true")
        commands.append("sudo ip link set br-inet up")
        commands.append("sudo sysctl -w net.ipv4.ip_forward=1")
        commands.append("sudo iptables -t nat -C POSTROUTING -s 172.16.0.0/24 -o ens3 -j MASQUERADE 2>/dev/null || sudo iptables -t nat -A POSTROUTING -s 172.16.0.0/24 -o ens3 -j MASQUERADE")
        commands.append("sudo iptables -C FORWARD -s 172.16.0.0/24 -d 192.168.201.0/24 -j DROP 2>/dev/null || sudo iptables -I FORWARD 1 -s 172.16.0.0/24 -d 192.168.201.0/24 -j DROP")
        commands.append("sudo iptables -C FORWARD -s 172.16.0.0/24 -j ACCEPT 2>/dev/null || sudo iptables -A FORWARD -s 172.16.0.0/24 -j ACCEPT")
        commands.append("sudo iptables -C FORWARD -d 172.16.0.0/24 -j ACCEPT 2>/dev/null || sudo iptables -A FORWARD -d 172.16.0.0/24 -j ACCEPT")
        commands.append("pgrep -f 'dnsmasq.*br-inet' >/dev/null || sudo dnsmasq --interface=br-inet --listen-address=172.16.0.1 --bind-interfaces --port=0 --dhcp-option=6,8.8.8.8,1.1.1.1 --dhcp-range=172.16.0.10,172.16.0.250,255.255.255.0,12h 2>/dev/null || true")

        bridge_name = f"br-sl-{req.slice.id}"
        for iface in req.interfaces:
            br = iface.bridge_name or bridge_name
            commands.append(f"sudo ovs-vsctl --may-exist add-br {br}")

        # --- 3. TAPs con Vlan-Inner ---
        has_remote = False
        for iface in req.interfaces:
            br = iface.bridge_name or bridge_name
            commands.append(f"sudo ip tuntap add mode tap {iface.tap_name} 2>/dev/null || true")
            commands.append(f"sudo ip link set {iface.tap_name} up")
            
            if iface.vlan_inner and iface.vlan_inner > 0:
                commands.append(f"sudo ovs-vsctl --may-exist add-port {br} {iface.tap_name} tag={iface.vlan_inner}")
            else:
                commands.append(f"sudo ovs-vsctl --may-exist add-port {br} {iface.tap_name}")
            rollback_actions.append(f"sudo ovs-vsctl --if-exists del-port {br} {iface.tap_name}")
            if iface.is_remote and br != "br-inet":
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

        # --- 5. Lanzar QEMU ---
        vnc_display = req.vm.id
        vnc_port = 5900 + vnc_display
        sorted_ifaces = sorted(req.interfaces, key=lambda x: x.interface_name)

        qemu_parts = [
            "sudo qemu-system-x86_64",
            "-enable-kvm",
            f"-m {req.vm.ram}",
            f"-smp {req.vm.vcpu}",
            f"{req.vm.instance_path}",
            f"-drive file={seed_path},media=cdrom,readonly=on",
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

        # 2. Remove instance disk & seed iso
        commands.append(f"sudo rm -f {req.vm.instance_path} /mnt/storage/instances/{req.vm.name}-seed.iso /tmp/user-data-{req.vm.name} /tmp/meta-data-{req.vm.name}")

        # 3. Remove pidfile
        commands.append(f"sudo rm -f /tmp/{req.vm.name}.pid")

        # 4. Delete TAPs
        bridge_name = f"br-sl-{req.slice.id}"
        for iface in req.interfaces:
            br = iface.bridge_name or bridge_name
            commands.append(f"sudo ovs-vsctl --if-exists del-port {br} {iface.tap_name}")
            commands.append(f"sudo ip link delete {iface.tap_name} 2>/dev/null || true")

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
    # Helpers
    # ==================================================================
    async def _rollback(self, worker_ip: str, actions: List[str]) -> List[CommandResult]:
        """Ejecuta acciones de rollback en orden inverso. Best-effort."""
        if not actions:
            return []
        logger.warning(f"Executing rollback ({len(actions)} actions) on {worker_ip}")
        results = await execute_on_worker(worker_ip, list(reversed(actions)))
        return results

