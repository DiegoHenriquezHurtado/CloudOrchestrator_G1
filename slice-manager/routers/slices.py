import os
import httpx
from fastapi import APIRouter, Depends, HTTPException, Header
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.future import select
from sqlalchemy.orm import selectinload
from sqlalchemy import text
from typing import List

from database import get_db
import models, schemas

router = APIRouter()

IMAGE_MANAGER_URL = os.getenv("IMAGE_MANAGER_URL", "http://image-manager:8083")
NETWORKING_URL = os.getenv("NETWORKING_URL", "http://networking:8085")
PLACEMENT_URL = os.getenv("PLACEMENT_URL", "http://vm-placement:8086")
DRIVER_URL = os.getenv("DRIVER_URL", "http://driver:8088")

async def get_current_user(x_user_role: str = Header(...), x_user_id: int = Header(...), db: AsyncSession = Depends(get_db)):
    result = await db.execute(select(models.User).where(models.User.id == x_user_id))
    user = result.scalar_one_or_none()
    if not user:
        raise HTTPException(status_code=403, detail="User not found")
    if user.role != x_user_role:
        raise HTTPException(status_code=403, detail="Role mismatch")
    return user

# ---------------------------------------------------------------------------
# POST /slices/ — Crear solicitud (STUDENT)
# ---------------------------------------------------------------------------
# Flujo: Validar imágenes → Insertar slice + VMs en PENDING_APPROVAL
#        → Guardar topología (links) como JSON para la fase de aprobación.
#        NO se llama a Networking aquí (se hará tras el Placement en approve).
# ---------------------------------------------------------------------------
@router.post("/", response_model=schemas.SliceCreateResponse, status_code=201)
async def create_slice(
    slice_in: schemas.SliceCreate,
    x_user_role: str = Header(...),
    x_user_id: int = Header(...),
    db: AsyncSession = Depends(get_db)
):
    user = await get_current_user(x_user_role, x_user_id, db)
    if user.role != "STUDENT":
        raise HTTPException(status_code=403, detail="Only students can create slices")

    # Validate quotas
    total_ram = sum(vm.ram for vm in slice_in.vms)
    total_vcpu = sum(vm.vcpu for vm in slice_in.vms)
    
    if total_ram > user.quota_ram or total_vcpu > user.quota_cpu:
        raise HTTPException(status_code=403, detail="Quota exceeded")

    # Validate images with Image Manager
    async with httpx.AsyncClient() as client:
        for vm in slice_in.vms:
            try:
                res = await client.get(f"{IMAGE_MANAGER_URL}/images/{vm.base_image}/validate")
                if res.status_code != 200:
                    raise HTTPException(status_code=400, detail=f"Image {vm.base_image} invalid or not found")
            except httpx.RequestError:
                raise HTTPException(status_code=503, detail="Image Manager service unavailable")

    # Persist topology links as JSON for the approval phase
    topology_links = [link.model_dump() for link in slice_in.links]

    new_slice = models.Slice(
        user_id=user.id,
        name=slice_in.name,
        topology=topology_links,
        status="PENDING_APPROVAL"
    )
    db.add(new_slice)
    await db.flush()

    vm_records = {}
    for vm in slice_in.vms:
        new_vm = models.VirtualMachine(
            slice_id=new_slice.id,
            name=vm.name,
            base_image=vm.base_image,
            ram=vm.ram,
            vcpu=vm.vcpu,
            status="PENDING_APPROVAL"
        )
        db.add(new_vm)
        await db.flush()
        vm_records[vm.name] = new_vm

    await db.commit()
    await db.refresh(new_slice)

    vms_response = [
        schemas.SliceResponseVM(id=vm_records[v].id, name=vm_records[v].name, status=vm_records[v].status)
        for v in vm_records
    ]
    return schemas.SliceCreateResponse(
        slice_id=new_slice.id,
        name=new_slice.name,
        status=new_slice.status,
        vms=vms_response,
        links_count=len(slice_in.links)
    )

# ---------------------------------------------------------------------------
# GET /slices/ — Listar slices del usuario autenticado
# ---------------------------------------------------------------------------
@router.get("/", response_model=schemas.SliceListResponse)
async def list_slices(
    x_user_role: str = Header(...),
    x_user_id: int = Header(...),
    db: AsyncSession = Depends(get_db)
):
    user = await get_current_user(x_user_role, x_user_id, db)
    
    if user.role == "STUDENT":
        result = await db.execute(select(models.Slice).options(selectinload(models.Slice.vms)).where(models.Slice.user_id == user.id))
    elif user.role == "SLICE_ADMIN":
        students_res = await db.execute(select(models.User.id).where(models.User.admin_id == user.id))
        student_ids = [row[0] for row in students_res.all()]
        result = await db.execute(select(models.Slice).options(selectinload(models.Slice.vms)).where(models.Slice.user_id.in_(student_ids)))
    else:
        result = await db.execute(select(models.Slice).options(selectinload(models.Slice.vms)))
        
    slices = result.scalars().all()
    
    response = []
    for s in slices:
        response.append(schemas.SliceListResponseItem(
            id=s.id,
            name=s.name,
            status=s.status,
            vms_count=len(s.vms),
            created_at=s.created_at.isoformat() if s.created_at else ""
        ))
        
    return schemas.SliceListResponse(slices=response)

# ---------------------------------------------------------------------------
# GET /slices/{id} — Detalle con VMs, IPs, PIDs, VNC ports
# ---------------------------------------------------------------------------
@router.get("/{id}", response_model=schemas.SliceDetailResponse)
async def get_slice(
    id: int,
    x_user_role: str = Header(...),
    x_user_id: int = Header(...),
    db: AsyncSession = Depends(get_db)
):
    user = await get_current_user(x_user_role, x_user_id, db)
    
    result = await db.execute(
        select(models.Slice)
        .options(
            selectinload(models.Slice.vms).selectinload(models.VirtualMachine.interfaces)
        )
        .where(models.Slice.id == id)
    )
    slice_obj = result.scalar_one_or_none()
    
    if not slice_obj:
        raise HTTPException(status_code=404, detail="Slice not found")

    if user.role == "STUDENT" and slice_obj.user_id != user.id:
        raise HTTPException(status_code=403, detail="Not authorized")
        
    if user.role == "SLICE_ADMIN":
        student_res = await db.execute(select(models.User).where(models.User.id == slice_obj.user_id))
        student = student_res.scalar_one_or_none()
        if not student or student.admin_id != user.id:
            raise HTTPException(status_code=403, detail="Not authorized")

    vms = []
    for vm in slice_obj.vms:
        interfaces = []
        for iface in vm.interfaces:
            net_res = await db.execute(select(models.Network).where(models.Network.id == iface.network_id))
            net = net_res.scalar_one_or_none()
            interfaces.append(schemas.VmInterfaceDetail(
                interface_name=iface.interface_name,
                ip_address=iface.ip_address,
                tap_name=iface.tap_name,
                vlan_inner=net.vlan_inner if net else None
            ))
            
        vms.append(schemas.VMDetail(
            id=vm.id,
            name=vm.name,
            worker_id=vm.worker_id,
            status=vm.status,
            process_id=vm.process_id,
            vnc_port=vm.vnc_port,
            interfaces=interfaces
        ))

    return schemas.SliceDetailResponse(
        id=slice_obj.id,
        name=slice_obj.name,
        status=slice_obj.status,
        vlan_slice=slice_obj.vlan_slice,
        topology=slice_obj.topology or [],
        vms=vms
    )

# ---------------------------------------------------------------------------
# POST /slices/{id}/approve — Aprobar Slice (SLICE_ADMIN)
# ---------------------------------------------------------------------------
# Flujo contractual:
#   1. Validar permisos (SLICE_ADMIN es dueño del alumno)
#   2. Crear tareas CREATE_VM en PENDING para cada VM
#   3. Invocar VM Placement (POST /placement/trigger) → asigna workers
#   4. Re-leer VMs con worker_id asignado
#   5. Invocar Networking (POST /networking/allocate) con placement_map real
#   6. Enriquecer el payload de cada tarea con datos completos
#   7. Actualizar slice a ACTIVE
# ---------------------------------------------------------------------------
@router.post("/{id}/approve", response_model=schemas.MessageResponse)
async def approve_slice(
    id: int,
    x_user_role: str = Header(...),
    x_user_id: int = Header(...),
    db: AsyncSession = Depends(get_db)
):
    user = await get_current_user(x_user_role, x_user_id, db)
    
    if user.role != "SLICE_ADMIN":
        raise HTTPException(status_code=403, detail="Only SLICE_ADMIN can approve")

    result = await db.execute(select(models.Slice).options(selectinload(models.Slice.vms)).where(models.Slice.id == id))
    slice_obj = result.scalar_one_or_none()
    if not slice_obj:
        raise HTTPException(status_code=404, detail="Slice not found")
        
    if slice_obj.status != "PENDING_APPROVAL":
        raise HTTPException(status_code=409, detail="Slice already processed")

    student_res = await db.execute(select(models.User).where(models.User.id == slice_obj.user_id))
    student = student_res.scalar_one_or_none()
    if not student or student.admin_id != user.id:
        if user.role != "SYSTEM_ADMIN":
            raise HTTPException(status_code=403, detail="Not authorized to approve this student's slice")

    # --- Paso 1: Crear tareas en PENDING y cambiar VMs a PENDING ---
    tasks_created = 0
    for vm in slice_obj.vms:
        vm.status = "PENDING"
        task = models.Task(
            slice_id=slice_obj.id,
            vm_id=vm.id,
            task_type="CREATE_VM",
            status="PENDING",
            payload={
                "vm_name": vm.name,
                "base_image": vm.base_image,
                "ram": vm.ram,
                "vcpu": vm.vcpu,
                "slice_id": slice_obj.id
            }
        )
        db.add(task)
        tasks_created += 1

    # Commit para que VM Placement pueda ver las tareas PENDING
    await db.commit()

    # --- Paso 2: Invocar VM Placement para asignar workers (Round Robin) ---
    placement_success = False
    async with httpx.AsyncClient(timeout=30.0) as client:
        try:
            res = await client.post(f"{PLACEMENT_URL}/placement/trigger")
            if res.status_code == 200:
                placement_success = True
        except httpx.RequestError:
            pass  # Si Placement no responde, las tareas quedan en PENDING para el loop

    # --- Paso 3: Re-leer VMs con worker_id asignado ---
    await db.refresh(slice_obj)
    vm_result = await db.execute(
        select(models.VirtualMachine).where(models.VirtualMachine.slice_id == slice_obj.id)
    )
    vms_updated = vm_result.scalars().all()

    # Construir placement_map: {vm_id: worker_id}
    placement_map = {}
    all_placed = True
    for vm in vms_updated:
        if vm.worker_id:
            placement_map[str(vm.id)] = vm.worker_id
        else:
            placement_map[str(vm.id)] = 0
            all_placed = False

    # --- Paso 4: Invocar Networking con placement_map real ---
    networking_response = None
    topology_links = slice_obj.topology or []

    if topology_links:
        # Convertir links de {vm_a: "VM1", ...} a {vm_a_id: 1, ...}
        vm_name_to_id = {vm.name: vm.id for vm in vms_updated}
        networking_links = []
        for i, link in enumerate(topology_links):
            vm_a_id = vm_name_to_id.get(link.get("vm_a"))
            vm_b_id = vm_name_to_id.get(link.get("vm_b"))
            if vm_a_id and vm_b_id:
                networking_links.append({
                    "link_name": f"link_{i}",
                    "vm_a_id": vm_a_id,
                    "iface_a": link.get("iface_a", "eth0"),
                    "vm_b_id": vm_b_id,
                    "iface_b": link.get("iface_b", "eth0"),
                    "internet_access": link.get("internet_access", False)
                })

        networking_payload = {
            "slice_id": slice_obj.id,
            "placement_map": placement_map,
            "links": networking_links
        }

        async with httpx.AsyncClient(timeout=30.0) as client:
            try:
                res = await client.post(f"{NETWORKING_URL}/networking/allocate", json=networking_payload)
                if res.status_code == 200:
                    networking_response = res.json()
            except httpx.RequestError:
                pass  # Networking se puede invocar después vía Dispatcher

    # --- Paso 5: Enriquecer payloads de las tareas con datos completos ---
    vlan_slice = None
    bridge_name = None
    if networking_response:
        vlan_slice = networking_response.get("vlan_slice")
        bridge_name = networking_response.get("bridge_name")
        slice_obj.vlan_slice = vlan_slice

    # Re-leer tareas + interfaces de cada VM para enriquecer
    tasks_res = await db.execute(
        select(models.Task).where(
            models.Task.slice_id == slice_obj.id,
            models.Task.task_type == "CREATE_VM"
        )
    )
    tasks = tasks_res.scalars().all()

    for task in tasks:
        vm = next((v for v in vms_updated if v.id == task.vm_id), None)
        if not vm:
            continue

        # Obtener interfaces de la VM desde la BD (insertadas por Networking)
        ifaces_res = await db.execute(
            select(models.VmInterface).where(models.VmInterface.vm_id == vm.id)
        )
        ifaces = ifaces_res.scalars().all()

        interfaces_payload = []
        for iface in ifaces:
            # Obtener datos de la red asociada
            net_res = await db.execute(
                select(models.Network).where(models.Network.id == iface.network_id)
            )
            net = net_res.scalar_one_or_none()
            interfaces_payload.append({
                "interface_name": iface.interface_name,
                "tap_name": iface.tap_name,
                "vlan_inner": net.vlan_inner if net else 0,
                "ip_address": iface.ip_address,
                "mac_address": iface.mac_address,
                "network_id": iface.network_id,
                "is_remote": net.is_remote if net else False,
                "internet_access": net.internet_access if net else False
            })

        instance_path = f"/mnt/storage/instances/{vm.id}.qcow2"
        vm.instance_path = instance_path

        # Payload completo según payload_schema.md
        task.payload = {
            "vm_name": vm.name,
            "base_image": vm.base_image,
            "base_path": f"/mnt/storage/base/{vm.base_image}",
            "instance_path": instance_path,
            "ram": vm.ram,
            "vcpu": vm.vcpu,
            "slice_id": slice_obj.id,
            "vlan_slice": vlan_slice,
            "bridge_name": bridge_name or f"br-sl-{slice_obj.id}",
            "interfaces": interfaces_payload
        }

    slice_obj.status = "ACTIVE"
    await db.commit()
    
    status_detail = "ACTIVE"
    msg_parts = [f"Slice aprobado. {tasks_created} tareas de tipo CREATE_VM generadas."]
    if placement_success and all_placed:
        msg_parts.append("Placement completado.")
    elif not placement_success:
        msg_parts.append("Placement pendiente (servicio no disponible, las tareas serán procesadas por el loop).")
    if networking_response:
        msg_parts.append(f"Networking asignado (Vlan-Slice: {vlan_slice}).")
    else:
        msg_parts.append("Networking pendiente (será asignado por el Dispatcher).")

    return schemas.MessageResponse(
        slice_id=slice_obj.id,
        status=status_detail,
        message=" ".join(msg_parts),
        tasks_created=tasks_created
    )

# ---------------------------------------------------------------------------
# POST /slices/{id}/reject — Rechazar Slice (SLICE_ADMIN)
# ---------------------------------------------------------------------------
@router.post("/{id}/reject", response_model=schemas.MessageResponse)
async def reject_slice(
    id: int,
    x_user_role: str = Header(...),
    x_user_id: int = Header(...),
    db: AsyncSession = Depends(get_db)
):
    user = await get_current_user(x_user_role, x_user_id, db)
    if user.role != "SLICE_ADMIN":
        raise HTTPException(status_code=403, detail="Only SLICE_ADMIN can reject")

    result = await db.execute(select(models.Slice).where(models.Slice.id == id))
    slice_obj = result.scalar_one_or_none()
    if not slice_obj:
        raise HTTPException(status_code=404, detail="Slice not found")

    if slice_obj.status != "PENDING_APPROVAL":
        raise HTTPException(status_code=409, detail="Slice already processed")

    slice_obj.status = "REJECTED"
    await db.commit()

    return schemas.MessageResponse(
        slice_id=slice_obj.id,
        status="REJECTED",
        message="Slice rechazado."
    )

# ---------------------------------------------------------------------------
# DELETE /slices/{id} — Borrado inteligente
# ---------------------------------------------------------------------------
@router.delete("/{id}")
async def delete_slice(
    id: int,
    x_user_role: str = Header(...),
    x_user_id: int = Header(...),
    db: AsyncSession = Depends(get_db)
):
    user = await get_current_user(x_user_role, x_user_id, db)

    if user.role not in ("SLICE_ADMIN", "SYSTEM_ADMIN"):
        raise HTTPException(status_code=403, detail="Only SLICE_ADMIN or SYSTEM_ADMIN can delete slices")

    result = await db.execute(select(models.Slice).options(selectinload(models.Slice.vms), selectinload(models.Slice.networks)).where(models.Slice.id == id))
    slice_obj = result.scalar_one_or_none()
    if not slice_obj:
        raise HTTPException(status_code=404, detail="Slice not found")

    if user.role == "SLICE_ADMIN":
        student_res = await db.execute(select(models.User).where(models.User.id == slice_obj.user_id))
        student = student_res.scalar_one_or_none()
        if not student or student.admin_id != user.id:
            raise HTTPException(status_code=403, detail="Not authorized to delete this student's slice")

    vms_count = len(slice_obj.vms)
    networks_count = len(slice_obj.networks)
    vlan_freed = slice_obj.vlan_slice

    # 1. Limpiar VMs en los workers sincrónicamente antes de borrar de la BD (para que pueda leer las interfaces)
    async with httpx.AsyncClient(timeout=60.0) as client:
        for vm in slice_obj.vms:
            if not vm.worker_id:
                continue

            worker_res = await db.execute(text(f"SELECT ip_management FROM workers WHERE id = {vm.worker_id}"))
            worker_ip = worker_res.scalar()
            if not worker_ip:
                continue

            ifaces_res = await db.execute(
                select(models.VmInterface).where(models.VmInterface.vm_id == vm.id)
            )
            ifaces = ifaces_res.scalars().all()
            
            interfaces_payload = []
            for iface in ifaces:
                net_res = await db.execute(
                    select(models.Network).where(models.Network.id == iface.network_id)
                )
                net = net_res.scalar_one_or_none()
                interfaces_payload.append({
                    "interface_name": iface.interface_name,
                    "tap_name": iface.tap_name,
                    "vlan_inner": net.vlan_inner if net else 0,
                    "ip_address": iface.ip_address,
                    "mac_address": iface.mac_address,
                    "bridge_name": f"br-sl-{id}",
                    "is_remote": net.is_remote if net else False,
                    "internet_access": net.internet_access if net else False
                })

            driver_request = {
                "task_id": 0,
                "task_type": "DELETE_VM",
                "worker_ip": worker_ip,
                "process_id": vm.process_id,
                "vm": {
                    "id": vm.id,
                    "name": vm.name,
                    "base_image": vm.base_image,
                    "ram": vm.ram,
                    "vcpu": vm.vcpu,
                    "instance_path": vm.instance_path or f"/mnt/storage/instances/{vm.id}.qcow2",
                },
                "slice": {
                    "id": slice_obj.id,
                    "vlan_slice": slice_obj.vlan_slice or 0,
                },
                "interfaces": interfaces_payload
            }

            try:
                await client.post(f"{DRIVER_URL}/driver/execute", json=driver_request)
            except httpx.RequestError:
                pass  # Best-effort deletion

    # 2. Liberar recursos de Networking si existen en la BD
    if vlan_freed:
        async with httpx.AsyncClient(timeout=10.0) as client:
            try:
                await client.post(
                    f"{NETWORKING_URL}/networking/release",
                    json={"slice_id": id}
                )
            except httpx.RequestError:
                pass  # Best-effort release

    await db.delete(slice_obj)
    
    if vlan_freed:
        vlan = await db.execute(select(models.VlanPool).where(models.VlanPool.vlan_id == vlan_freed))
        v = vlan.scalar_one_or_none()
        if v:
            v.status = "AVAILABLE"

    await db.commit()

    return {
        "slice_id": id,
        "status": "DELETED",
        "cleanup": {
            "vms_terminated": vms_count,
            "networks_released": networks_count,
            "vlan_slice_freed": vlan_freed
        }
    }
