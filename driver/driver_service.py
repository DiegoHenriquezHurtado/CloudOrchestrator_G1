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
        commands.append(f"sudo qemu-img create -f qcow2 -b {base_path} {req.vm.instance_path}")
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
            if iface.vlan_inner and iface.vlan_inner > 0:
                commands.append(f"sudo ovs-vsctl add-port {bridge_name} {iface.tap_name} tag={iface.vlan_inner}")
            else:
                commands.append(f"sudo ovs-vsctl add-port {bridge_name} {iface.tap_name}")
            rollback_actions.append(f"sudo ovs-vsctl --if-exists del-port {bridge_name} {iface.tap_name}")
            if iface.is_remote:
                has_remote = True

        # --- 4. Patch Ports (solo si hay enlaces remotos) ---
        if has_remote and req.slice.vlan_slice:
            patch_wk = f"patch-to-wk-{req.slice.id}"
            patch_sl = f"patch-to-sl-{req.slice.id}"
            commands.append(
                f"sudo ovs-vsctl --may-exist add-port {bridge_name} {patch_wk} "
                f"-- set interface {patch_wk} type=patch options:peer={patch_sl}"
            )
            commands.append(
                f"sudo ovs-vsctl --may-exist add-port br-wk {patch_sl} tag={req.slice.vlan_slice} "
                f"-- set interface {patch_sl} type=patch options:peer={patch_wk}"
            )

        # --- 5. Lanzar QEMU ---
        vnc_display = req.vm.id
        vnc_port = 5900 + vnc_display

        qemu_parts = [
            "SEED_OPT=\"\"; if [ -f /mnt/storage/base/seed.iso ]; then SEED_OPT=\"-drive file=/mnt/storage/base/seed.iso,media=cdrom,readonly=on\"; fi; "
            "sudo qemu-system-x86_64 $SEED_OPT",
            f"-m {req.vm.ram}",
            f"-smp {req.vm.vcpu}",
            f"-drive file={req.vm.instance_path},format=qcow2",
        ]

        for i, iface in enumerate(req.interfaces):
            qemu_parts.append(f"-netdev tap,id=net{i},ifname={iface.tap_name},script=no,downscript=no")
            qemu_parts.append(f"-device virtio-net-pci,netdev=net{i},mac={iface.mac_address}")

        qemu_parts.extend([
            f"-pidfile /tmp/{req.vm.name}.pid",
            f"-vnc :{vnc_display}",
            "-daemonize",
        ])

        qemu_cmd = " \\\n  ".join(qemu_parts)
        commands.append(qemu_cmd)

        # --- 6. Leer PID ---
        commands.append(f"sudo cat /tmp/{req.vm.name}.pid")

        # --- Ejecutar ---
        results = await execute_on_worker(req.worker_ip, commands)

        # Verificar resultados
        failed_result = next((r for r in results if not r.success), None)
        if failed_result:
            # Rollback
            rb_results = await self._rollback(req.worker_ip, rollback_actions)
            return ExecuteFailureResponse(
                task_id=req.task_id,
                status="FAILED",
                error_msg=f"Command failed: {failed_result.command[:100]} — {failed_result.stderr[:200]}",
                rollback_actions=[f"Executed: {r.command}" for r in rb_results],
            )

        # Extraer PID del último comando (cat /tmp/VM.pid)
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

        # 5. Delete patch-ports if remote
        has_remote = any(iface.is_remote for iface in req.interfaces)
        if has_remote:
            patch_wk = f"patch-to-wk-{req.slice.id}"
            patch_sl = f"patch-to-sl-{req.slice.id}"
            commands.append(f"sudo ovs-vsctl --if-exists del-port {bridge_name} {patch_wk}")
            commands.append(f"sudo ovs-vsctl --if-exists del-port br-wk {patch_sl}")

        # 6. Delete bridge if empty (check if only has patch ports or none)
        commands.append(
            f"port_count=$(sudo ovs-vsctl list-ports {bridge_name} 2>/dev/null | wc -l); "
            f"if [ \"$port_count\" -eq 0 ]; then sudo ovs-vsctl --if-exists del-br {bridge_name}; fi"
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
