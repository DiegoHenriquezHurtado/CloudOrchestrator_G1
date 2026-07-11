"""
Dispatcher Service — Lógica de polling, enriquecimiento y despacho de tareas.

Responsabilidades:
  1. Poll: busca tareas con status='PLACEMENT_READY'
  2. Lock: transiciona a 'IN_PROGRESS' para evitar duplicados
  3. Enrich: si el payload no tiene interfaces/vlan_slice, consulta la BD y/o Networking
  4. Dispatch: envía POST /driver/execute con el payload completo
  5. Finalize: actualiza tarea a READY/FAILED y persiste PID/VNC en virtual_machines
"""

import os
import httpx
import logging
from datetime import datetime, timedelta
from sqlalchemy import select, func
from sqlalchemy.ext.asyncio import AsyncSession

from models import Task, VirtualMachine, Slice, Worker, Network, VmInterface

logger = logging.getLogger("dispatcher")

DRIVER_URL = os.getenv("DRIVER_URL", "http://driver:8088")
OPENSTACK_DRIVER_URL = os.getenv("OPENSTACK_DRIVER_URL", "http://openstack-driver:8089")
NETWORKING_URL = os.getenv("NETWORKING_URL", "http://networking:8085")
STALE_TIMEOUT_MINUTES = int(os.getenv("STALE_TIMEOUT_MINUTES", "10"))


class DispatcherService:

    # ------------------------------------------------------------------
    # GET /dispatcher/status
    # ------------------------------------------------------------------
    async def get_status(self, db: AsyncSession) -> dict:
        in_progress = await db.scalar(
            select(func.count()).select_from(Task).where(Task.status == "IN_PROGRESS")
        )
        one_hour_ago = datetime.utcnow() - timedelta(hours=1)
        completed = await db.scalar(
            select(func.count()).select_from(Task).where(
                Task.status == "READY", Task.updated_at >= one_hour_ago
            )
        )
        failed = await db.scalar(
            select(func.count()).select_from(Task).where(
                Task.status == "FAILED", Task.updated_at >= one_hour_ago
            )
        )
        return {
            "polling_active": True,
            "tasks_in_progress": in_progress or 0,
            "tasks_completed_last_hour": completed or 0,
            "tasks_failed_last_hour": failed or 0,
        }

    # ------------------------------------------------------------------
    # POST /dispatcher/trigger  +  background polling loop
    # ------------------------------------------------------------------
    async def process_tasks(self, db: AsyncSession) -> dict:
        # --- Recover stale tasks (keep-alive) ---
        await self._recover_stale_tasks(db)

        # --- Fetch PLACEMENT_READY tasks ---
        result = await db.execute(
            select(Task).where(Task.status == "PLACEMENT_READY").order_by(Task.created_at)
        )
        tasks = result.scalars().all()

        dispatched = []
        errors = []

        for task in tasks:
            try:
                dispatch_result = await self._dispatch_single(task, db)
                dispatched.append(dispatch_result)
            except Exception as e:
                logger.error(f"Task {task.id} dispatch failed: {e}")
                task.status = "FAILED"
                task.error_msg = str(e)[:500]
                task.updated_at = datetime.utcnow()
                await db.commit()
                errors.append({"task_id": task.id, "error": str(e)[:200]})

        return {"dispatched": dispatched, "errors": errors}

    # ------------------------------------------------------------------
    # Dispatch a single task
    # ------------------------------------------------------------------
    async def _dispatch_single(self, task: Task, db: AsyncSession) -> dict:
        # 1. Lock → IN_PROGRESS
        task.status = "IN_PROGRESS"
        task.updated_at = datetime.utcnow()
        await db.commit()

        # 2. Load related entities
        vm = await self._get_vm(task.vm_id, db)
        slice_obj = await self._get_slice(task.slice_id, db)

        if not vm or not slice_obj:
            raise ValueError(f"Missing entity: vm={task.vm_id}, slice={task.slice_id}")

        # --- REDIRECCIÓN DE OPENSTACK ---
        if slice_obj.iaas_target == "openstack":
            # Si el slice/VM ya fue procesado y completado exitosamente por otra tarea del mismo slice
            if vm.status == "READY":
                task.status = "READY"
                task.updated_at = datetime.utcnow()
                await db.commit()
                return {
                    "task_id": task.id,
                    "vm_id": vm.id,
                    "status": "READY"
                }

            # Obtener todas las VMs del slice para verificar sus workers asignados
            vms_res = await db.execute(
                select(VirtualMachine).where(VirtualMachine.slice_id == slice_obj.id)
            )
            vms_list = vms_res.scalars().all()
            
            # Mapear worker_id -> hostname
            worker_id_to_hostname = {}
            for v_db in vms_list:
                if v_db.worker_id and v_db.worker_id not in worker_id_to_hostname:
                    w_res = await db.execute(select(Worker.hostname).where(Worker.id == v_db.worker_id))
                    hname = w_res.scalar_one_or_none()
                    if hname:
                        worker_id_to_hostname[v_db.worker_id] = hname
                        
            # Modificar payload para añadir el campo "host" a cada VM
            payload = dict(task.payload)
            vms_payload = []
            for vm_p in payload.get("vms", []):
                vm_p_copy = dict(vm_p)
                v_db = next((v for v in vms_list if v.name == vm_p_copy.get("name")), None)
                if v_db and v_db.worker_id in worker_id_to_hostname:
                    vm_p_copy["host"] = worker_id_to_hostname[v_db.worker_id]
                vms_payload.append(vm_p_copy)
            payload["vms"] = vms_payload

            driver_url = f"{OPENSTACK_DRIVER_URL}/v1/vms/create"
            logger.info(f"Enviando solicitud de creación de slice {slice_obj.name} a OpenStack Driver: {driver_url}")
            
            async with httpx.AsyncClient(timeout=180.0) as client:
                res = await client.post(driver_url, json=payload)
                
            driver_response = res.json()
            
            if res.status_code in [200, 201] and driver_response.get("status") == "READY":
                # Provisión exitosa: actualizamos todas las VMs del slice
                vms_res = await db.execute(
                    select(VirtualMachine).where(VirtualMachine.slice_id == slice_obj.id)
                )
                vms_list = vms_res.scalars().all()
                
                returned_vms = {v["name"]: v for v in driver_response.get("vms", [])}
                for v_db in vms_list:
                    ret_vm = returned_vms.get(v_db.name)
                    if ret_vm:
                        v_db.status = "READY"
                        v_db.instance_path = ret_vm.get("server_id")  # UUID del servidor en OpenStack
                        v_db.vnc_url = ret_vm.get("vnc_url")
                        
                # Marcamos todas las tareas CREATE_VM del slice como READY
                tasks_res = await db.execute(
                    select(Task).where(Task.slice_id == slice_obj.id, Task.task_type == "CREATE_VM")
                )
                slice_tasks = tasks_res.scalars().all()
                for t in slice_tasks:
                    t.status = "READY"
                    t.updated_at = datetime.utcnow()
                    
                await db.commit()
                logger.info(f"Slice de OpenStack {slice_obj.name} completado con éxito en base de datos.")
            else:
                # Provisión fallida: marcamos todo como FAILED
                error_detail = driver_response.get("detail", {})
                error_msg = error_detail.get("message", f"OpenStack driver returned status code {res.status_code}") if isinstance(error_detail, dict) else str(error_detail)
                
                vms_res = await db.execute(
                    select(VirtualMachine).where(VirtualMachine.slice_id == slice_obj.id)
                )
                for v_db in vms_res.scalars().all():
                    v_db.status = "FAILED"
                    
                tasks_res = await db.execute(
                    select(Task).where(Task.slice_id == slice_obj.id, Task.task_type == "CREATE_VM")
                )
                for t in tasks_res.scalars().all():
                    t.status = "FAILED"
                    t.error_msg = str(error_msg)[:500]
                    t.updated_at = datetime.utcnow()
                    
                await db.commit()
                logger.error(f"Fallo en aprovisionamiento de Slice de OpenStack: {error_msg}")
                raise Exception(f"OpenStack provisioning failed: {error_msg}")

            return {
                "task_id": task.id,
                "vm_id": vm.id,
                "status": "READY"
            }

        # --- FLUJO ESTÁNDAR LINUX ---
        worker = await self._get_worker(task.worker_id, db)
        if not worker:
            raise ValueError(f"Missing entity: worker={task.worker_id}")

        # 3. Ensure payload is enriched (fallback if Networking wasn't called)
        payload = task.payload or {}
        if not payload.get("interfaces") or not payload.get("vlan_slice"):
            payload = await self._enrich_payload(task, vm, slice_obj, db)
            task.payload = payload
            await db.commit()

        # 4. Build Driver request
        bridge_name = payload.get("bridge_name", f"br-sl-{slice_obj.id}")

        driver_request = {
            "task_id": task.id,
            "task_type": task.task_type,
            "worker_ip": worker.ip_management,
            "vm": {
                "id": vm.id,
                "name": vm.name,
                "base_image": vm.base_image,
                "ram": vm.ram,
                "vcpu": vm.vcpu,
                "disk": payload.get("disk", 0),
                "instance_path": payload.get("instance_path", f"/mnt/storage/instances/{vm.id}.qcow2")
            },
            "slice": {
                "id": slice_obj.id,
                "vlan_slice": payload.get("vlan_slice") or slice_obj.vlan_slice or 0,
            },
            "interfaces": [
                {
                    "interface_name": iface.get("interface_name", ""),
                    "tap_name": iface.get("tap_name", ""),
                    "vlan_inner": iface.get("vlan_inner", 0),
                    "mac_address": iface.get("mac_address", ""),
                    "bridge_name": iface.get("bridge_name") or bridge_name,
                    "is_remote": iface.get("is_remote", False),
                }
                for iface in payload.get("interfaces", [])
            ],
        }

        # For DELETE_VM, include process_id
        if task.task_type == "DELETE_VM":
            driver_request["process_id"] = vm.process_id

        # 5. Call Driver
        async with httpx.AsyncClient(timeout=120.0) as client:
            res = await client.post(f"{DRIVER_URL}/driver/execute", json=driver_request)

        driver_response = res.json()

        # 6. Handle response
        if res.status_code == 200 and driver_response.get("status") == "READY":
            await self._handle_success(task, vm, driver_response, db)
        else:
            error_msg = driver_response.get("error_msg", f"Driver returned {res.status_code}")
            await self._handle_failure(task, error_msg, db)

        return {
            "task_id": task.id,
            "vm_id": vm.id,
            "worker_ip": worker.ip_management,
            "status": task.status,
        }

    # ------------------------------------------------------------------
    # Enrich payload from DB + Networking (fallback path)
    # ------------------------------------------------------------------
    async def _enrich_payload(self, task: Task, vm: VirtualMachine,
                              slice_obj: Slice, db: AsyncSession) -> dict:
        payload = dict(task.payload) if task.payload else {}

        # If slice doesn't have vlan_slice, try calling Networking
        if not slice_obj.vlan_slice and slice_obj.topology:
            await self._call_networking_allocate(slice_obj, db)
            await db.refresh(slice_obj)

        # Read interfaces from DB
        ifaces_res = await db.execute(
            select(VmInterface).where(VmInterface.vm_id == vm.id)
        )
        ifaces = ifaces_res.scalars().all()

        interfaces_payload = []
        for iface in ifaces:
            net = None
            if iface.network_id:
                net_res = await db.execute(
                    select(Network).where(Network.id == iface.network_id)
                )
                net = net_res.scalar_one_or_none()
            interfaces_payload.append({
                "interface_name": iface.interface_name,
                "tap_name": iface.tap_name,
                "vlan_inner": net.vlan_inner if net else 0,
                "mac_address": iface.mac_address,
                "network_id": iface.network_id,
                "bridge_name": iface.bridge_name or f"br-sl-{slice_obj.id}",
                "is_remote": net.is_remote if net else False,
            })

        instance_path = f"/mnt/storage/instances/{vm.id}.qcow2"
        vm.instance_path = instance_path

        payload.update({
            "vm_name": vm.name,
            "base_image": vm.base_image,
            "base_path": f"/mnt/storage/base/{vm.base_image}",
            "instance_path": instance_path,
            "ram": vm.ram,
            "vcpu": vm.vcpu,
            "disk": vm.disk,
            "slice_id": slice_obj.id,
            "vlan_slice": slice_obj.vlan_slice,
            "bridge_name": f"br-sl-{slice_obj.id}",
            "interfaces": interfaces_payload,
        })
        return payload

    # ------------------------------------------------------------------
    # Call Networking allocate (fallback if Slice Manager didn't)
    # ------------------------------------------------------------------
    async def _call_networking_allocate(self, slice_obj: Slice, db: AsyncSession):
        vms_res = await db.execute(
            select(VirtualMachine).where(VirtualMachine.slice_id == slice_obj.id)
        )
        vms = vms_res.scalars().all()
        vm_name_to_id = {vm.name: vm.id for vm in vms}
        placement_map = {str(vm.id): vm.worker_id or 0 for vm in vms}

        topology = slice_obj.topology or []
        networking_links = []
        for i, link in enumerate(topology):
            vm_a_name = str(link.get("vm_a", "")).upper()
            vm_b_name = str(link.get("vm_b", "")).upper()
            vm_a_id = 0 if vm_a_name in ("INTERNET", "INET", "WAN", "EXTERNAL") else vm_name_to_id.get(link.get("vm_a"))
            vm_b_id = 0 if vm_b_name in ("INTERNET", "INET", "WAN", "EXTERNAL") else vm_name_to_id.get(link.get("vm_b"))
            if vm_a_id is not None and vm_b_id is not None:
                networking_links.append({
                    "link_name": f"link_{i}",
                    "vm_a_id": vm_a_id,
                    "iface_a": link.get("iface_a", "eth0"),
                    "vm_b_id": vm_b_id,
                    "iface_b": link.get("iface_b", "eth0"),
                })

        payload = {
            "slice_id": slice_obj.id,
            "placement_map": placement_map,
            "links": networking_links,
        }

        try:
            async with httpx.AsyncClient(timeout=30.0) as client:
                res = await client.post(f"{NETWORKING_URL}/networking/allocate", json=payload)
                if res.status_code == 200:
                    data = res.json()
                    slice_obj.vlan_slice = data.get("vlan_slice")
                    await db.commit()
                    logger.info(f"Networking enrichment OK for slice {slice_obj.id}, vlan={slice_obj.vlan_slice}")
                else:
                    logger.warning(f"Networking allocate failed: {res.status_code}")
        except httpx.RequestError as e:
            logger.warning(f"Networking unreachable: {e}")

    # ------------------------------------------------------------------
    # Handle success / failure
    # ------------------------------------------------------------------
    async def _handle_success(self, task: Task, vm: VirtualMachine,
                              response: dict, db: AsyncSession):
        task.status = "READY"
        task.error_msg = None
        task.updated_at = datetime.utcnow()

        if task.task_type == "CREATE_VM":
            vm.process_id = response.get("process_id")
            vm.vnc_port = response.get("vnc_port")
            vm.status = "READY"

        await db.commit()
        logger.info(f"Task {task.id} completed: READY (pid={response.get('process_id')})")

    async def _handle_failure(self, task: Task, error_msg: str, db: AsyncSession):
        task.status = "FAILED"
        task.error_msg = error_msg[:500]
        task.updated_at = datetime.utcnow()
        await db.commit()
        logger.warning(f"Task {task.id} failed: {error_msg[:100]}")

    # ------------------------------------------------------------------
    # Recover stale IN_PROGRESS tasks (keep-alive)
    # ------------------------------------------------------------------
    async def _recover_stale_tasks(self, db: AsyncSession):
        cutoff = datetime.utcnow() - timedelta(minutes=STALE_TIMEOUT_MINUTES)
        result = await db.execute(
            select(Task).where(Task.status == "IN_PROGRESS", Task.updated_at < cutoff)
        )
        stale_tasks = result.scalars().all()
        for task in stale_tasks:
            logger.warning(f"Recovering stale task {task.id} (stuck since {task.updated_at})")
            task.status = "PLACEMENT_READY"
            task.error_msg = f"Reset: stale IN_PROGRESS (>{STALE_TIMEOUT_MINUTES}min)"
            task.updated_at = datetime.utcnow()
        if stale_tasks:
            await db.commit()

    # ------------------------------------------------------------------
    # DB helpers
    # ------------------------------------------------------------------
    async def _get_vm(self, vm_id: int, db: AsyncSession):
        res = await db.execute(select(VirtualMachine).where(VirtualMachine.id == vm_id))
        return res.scalar_one_or_none()

    async def _get_slice(self, slice_id: int, db: AsyncSession):
        res = await db.execute(select(Slice).where(Slice.id == slice_id))
        return res.scalar_one_or_none()

    async def _get_worker(self, worker_id: int, db: AsyncSession):
        res = await db.execute(select(Worker).where(Worker.id == worker_id))
        return res.scalar_one_or_none()
