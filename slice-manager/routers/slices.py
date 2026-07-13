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
# Activa un slice "linux" ya persistido: crea tareas CREATE_VM, invoca
# VM Placement y Networking, y enriquece los payloads. Deja el slice ACTIVE.
# Reutilizado por /approve (flujo STUDENT, PENDING_APPROVAL -> ACTIVE) y por
# /deploy (flujo SLICE_ADMIN/SYSTEM_ADMIN, DRAFT -> ACTIVE bajo demanda).
# ---------------------------------------------------------------------------
async def _activate_linux_slice(slice_obj: models.Slice, db: AsyncSession):
    tasks_created = 0
    for vm in slice_obj.vms:
        vm.status = "PENDING"
        task = models.Task(
            slice_id=slice_obj.id,
            vm_id=vm.id,
            task_type="CREATE_VM",
            status="PENDING",
            payload={
                "vm": {
                    "id": vm.id,
                    "name": vm.name,
                    "base_image": vm.base_image,
                    "ram": vm.ram,
                    "vcpu": vm.vcpu,
                    "disk": vm.disk,
                    "instance_path": ""
                },
                "slice": {
                    "id": slice_obj.id,
                    "vlan_slice": 0
                },
                "interfaces": []
            }
        )
        db.add(task)
        tasks_created += 1

    # Commit para que VM Placement pueda ver las tareas PENDING
    await db.commit()

    placement_success = False
    async with httpx.AsyncClient(timeout=30.0) as client:
        try:
            res = await client.post(f"{PLACEMENT_URL}/placement/trigger")
            if res.status_code == 200:
                placement_success = True
        except httpx.RequestError:
            pass  # Si Placement no responde, las tareas quedan en PENDING para el loop

    await db.refresh(slice_obj)
    vm_result = await db.execute(
        select(models.VirtualMachine).where(models.VirtualMachine.slice_id == slice_obj.id)
    )
    vms_updated = vm_result.scalars().all()

    placement_map = {}
    all_placed = True
    for vm in vms_updated:
        if vm.worker_id:
            placement_map[str(vm.id)] = vm.worker_id
        else:
            placement_map[str(vm.id)] = 0
            all_placed = False

    networking_response = None
    topology_links = slice_obj.topology or []

    if topology_links:
        vm_name_to_id = {vm.name: vm.id for vm in vms_updated}
        networking_links = []
        for i, link in enumerate(topology_links):
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
                    "iface_b": link.get("iface_b", "eth0")
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

    vlan_slice = None
    bridge_name = None
    if networking_response:
        vlan_slice = networking_response.get("vlan_slice")
        bridge_name = networking_response.get("bridge_name")
        slice_obj.vlan_slice = vlan_slice

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
                "mac_address": iface.mac_address,
                "bridge_name": iface.bridge_name or (f"br-sl-{slice_obj.id}" if net else "br-inet"),
                "network_id": iface.network_id,
                "is_remote": net.is_remote if net else False
            })

        instance_path = f"/mnt/storage/instances/{vm.id}.qcow2"
        vm.instance_path = instance_path

        task.payload = {
            "vm_name": vm.name,
            "base_image": vm.base_image,
            "base_path": f"/mnt/storage/base/{vm.base_image}",
            "instance_path": instance_path,
            "ram": vm.ram,
            "vcpu": vm.vcpu,
            "disk": vm.disk,
            "slice_id": slice_obj.id,
            "vlan_slice": vlan_slice,
            "bridge_name": bridge_name or f"br-sl-{slice_obj.id}",
            "interfaces": interfaces_payload
        }

    slice_obj.status = "ACTIVE"
    await db.commit()

    msg_parts = [f"{tasks_created} tareas de tipo CREATE_VM generadas."]
    if placement_success and all_placed:
        msg_parts.append("Placement completado.")
    elif not placement_success:
        msg_parts.append("Placement pendiente (servicio no disponible, las tareas serán procesadas por el loop).")
    if networking_response:
        msg_parts.append(f"Networking asignado (Vlan-Slice: {vlan_slice}).")
    else:
        msg_parts.append("Networking pendiente (será asignado por el Dispatcher).")

    return tasks_created, " ".join(msg_parts)

# ---------------------------------------------------------------------------
# Activa un slice "openstack" ya persistido: reconstruye el payload de VMs/
# redes desde la topología guardada, crea tareas CREATE_VM en PENDING (el
# mismo estado que vm-placement espera para asignarles worker) e invoca
# VM Placement. Deja el slice ACTIVE.
# Reutilizado por /deploy (flujo SLICE_ADMIN/SYSTEM_ADMIN, borrador -> activo)
# y por /approve para mantener un único punto de esta lógica.
# ---------------------------------------------------------------------------
async def _activate_openstack_slice(slice_obj: models.Slice, db: AsyncSession):
    topology = slice_obj.topology or {}
    links = topology.get("links", [])
    networks_in = topology.get("networks", [])

    networks_payload = []
    for net in networks_in:
        networks_payload.append({
            "name": net.get("name"),
            "cidr": net.get("cidr"),
            "is_provider": net.get("is_provider", False)
        })

    private_links = []
    for link in links:
        vm_a = link.get("vm_a", "")
        vm_b = link.get("vm_b", "")
        is_a_provider = vm_a.upper() in ["INTERNET", "INET", "WAN", "EXTERNAL", "EXTERNAL-PROVIDER"]
        is_b_provider = vm_b.upper() in ["INTERNET", "INET", "WAN", "EXTERNAL", "EXTERNAL-PROVIDER"]
        if not is_a_provider and not is_b_provider:
            private_links.append(link)

    private_networks = [n for n in networks_payload if not n["is_provider"]]
    link_net_map = {}
    for idx, link in enumerate(private_links):
        if idx < len(private_networks):
            link_net_map[idx] = private_networks[idx]["name"]

    vm_vms_payload = []
    for vm in slice_obj.vms:
        vm_networks = []
        for link in links:
            vm_a = link.get("vm_a", "")
            vm_b = link.get("vm_b", "")
            is_a_provider = vm_a.upper() in ["INTERNET", "INET", "WAN", "EXTERNAL", "EXTERNAL-PROVIDER"]
            is_b_provider = vm_b.upper() in ["INTERNET", "INET", "WAN", "EXTERNAL", "EXTERNAL-PROVIDER"]

            if vm_a == vm.name:
                if is_b_provider:
                    vm_networks.append(vm_b)
                else:
                    try:
                        l_idx = private_links.index(link)
                        net_name = link_net_map.get(l_idx)
                        if net_name:
                            vm_networks.append(net_name)
                    except ValueError:
                        pass
            elif vm_b == vm.name:
                if is_a_provider:
                    vm_networks.append(vm_a)
                else:
                    try:
                        l_idx = private_links.index(link)
                        net_name = link_net_map.get(l_idx)
                        if net_name:
                            vm_networks.append(net_name)
                    except ValueError:
                        pass

        # Remove duplicates preserving order, and sort so that provider/external networks always come first (map to eth0)
        unique_networks = list(dict.fromkeys(vm_networks))
        unique_networks.sort(key=lambda net: 0 if net.upper() in ["INTERNET", "INET", "WAN", "EXTERNAL", "EXTERNAL-PROVIDER"] else 1)
            
        vm_vms_payload.append({
            "name": vm.name,
            "image": vm.base_image,
            "flavor": vm.flavor,
            "networks": unique_networks
        })

    task_payload = {
        "slice_id": slice_obj.name,
        "vms": vm_vms_payload,
        "networks": networks_payload
    }

    tasks_created = 0
    for vm in slice_obj.vms:
        vm.status = "PENDING"
        task = models.Task(
            slice_id=slice_obj.id,
            vm_id=vm.id,
            task_type="CREATE_VM",
            status="PENDING",
            payload=task_payload
        )
        db.add(task)
        tasks_created += 1

    slice_obj.status = "ACTIVE"
    await db.commit()

    placement_message = "Placement pendiente (servicio no disponible, las tareas serán procesadas por el loop)."
    async with httpx.AsyncClient(timeout=30.0) as client:
        try:
            res = await client.post(f"{PLACEMENT_URL}/placement/trigger")
            if res.status_code == 200:
                placement_message = "Placement completado."
        except httpx.RequestError:
            pass

    return tasks_created, f"{tasks_created} tareas de tipo CREATE_VM generadas. {placement_message}"

# ---------------------------------------------------------------------------
# Valida flavor/imagen y crea las filas VirtualMachine de un slice (linux u
# openstack). Reutilizado por create_slice y por update_slice (edición de
# un Borrador, donde primero se borran las VMs previas y se reconstruyen).
# ---------------------------------------------------------------------------
async def _build_vms(slice_in: schemas.SliceCreate, user: models.User, slice_id: int, vm_status: str, db: AsyncSession):
    vm_records = {}
    async with httpx.AsyncClient() as client:
        for vm in slice_in.vms:
            ram = 0
            vcpu = 0
            disk = 0
            flavor_str = vm.flavor

            if slice_in.iaas_target == "linux":
                if not vm.flavor_id:
                    raise HTTPException(status_code=400, detail=f"flavor_id is required for linux VM {vm.name}")
                flavor_res = await db.execute(select(models.Flavor).where(models.Flavor.id == vm.flavor_id))
                flavor_obj = flavor_res.scalar_one_or_none()
                if not flavor_obj:
                    raise HTTPException(status_code=400, detail=f"Flavor ID {vm.flavor_id} not found")
                if user.role == "STUDENT" and flavor_obj.allowed_role != "STUDENT":
                    raise HTTPException(status_code=403, detail=f"Student cannot use flavor {flavor_obj.name}")

                ram = flavor_obj.ram
                vcpu = flavor_obj.vcpu
                disk = flavor_obj.disk

            elif slice_in.iaas_target == "openstack":
                if not vm.flavor:
                    raise HTTPException(status_code=400, detail=f"flavor (string) is required for openstack VM {vm.name}")

                # Dynamic fetch from Nova API
                OPENSTACK_DRIVER_URL = os.getenv("OPENSTACK_DRIVER_URL", "http://openstack-driver:8089")
                try:
                    os_res = await client.get(f"{OPENSTACK_DRIVER_URL}/v1/flavors/{vm.flavor}")
                    if os_res.status_code == 200:
                        os_flavor = os_res.json()
                        ram = os_flavor.get("ram", 0)
                        vcpu = os_flavor.get("vcpus", 0)
                        disk = os_flavor.get("disk", 0)
                    else:
                        raise HTTPException(status_code=400, detail=f"OpenStack flavor {vm.flavor} not found or error")
                except httpx.RequestError:
                    raise HTTPException(status_code=503, detail="OpenStack Driver unavailable")

            new_vm = models.VirtualMachine(
                slice_id=slice_id,
                name=vm.name,
                base_image=vm.base_image,
                ram=ram,
                vcpu=vcpu,
                disk=disk,
                flavor=flavor_str,
                flavor_id=vm.flavor_id,
                status=vm_status
            )
            db.add(new_vm)
            await db.flush()
            vm_records[vm.name] = new_vm
    return vm_records

# ---------------------------------------------------------------------------
# POST /slices/ — Crear slice (STUDENT: solicitud; SLICE_ADMIN/SYSTEM_ADMIN: borrador)
# ---------------------------------------------------------------------------
# Flujo: Validar imágenes → Insertar slice + VMs.
#        STUDENT: queda en PENDING_APPROVAL (requiere aprobación de SLICE_ADMIN).
#        SLICE_ADMIN/SYSTEM_ADMIN (linux u openstack): queda en DRAFT (Borrador).
#        No se invoca Placement/Networking/OpenStack aquí — eso ocurre recién
#        con POST /{id}/deploy, bajo demanda.
# ---------------------------------------------------------------------------
@router.post("/", response_model=schemas.SliceCreateResponse, status_code=201)
async def create_slice(
    slice_in: schemas.SliceCreate,
    x_user_role: str = Header(...),
    x_user_id: int = Header(...),
    db: AsyncSession = Depends(get_db)
):
    user = await get_current_user(x_user_role, x_user_id, db)
    
    if slice_in.iaas_target == "openstack":
        if user.role not in ["SLICE_ADMIN", "SYSTEM_ADMIN"]:
            raise HTTPException(status_code=403, detail="Only administrators can create slices on OpenStack")

    # Validate images with Image Manager (only for local linux target)
    if slice_in.iaas_target == "linux":
        async with httpx.AsyncClient() as client:
            for vm in slice_in.vms:
                try:
                    res = await client.get(f"{IMAGE_MANAGER_URL}/images/{vm.base_image}/validate")
                    if res.status_code != 200:
                        raise HTTPException(status_code=400, detail=f"Image {vm.base_image} invalid or not found")
                except httpx.RequestError:
                    raise HTTPException(status_code=503, detail="Image Manager service unavailable")

    # Persist topology links as JSON for the approval phase
    if slice_in.iaas_target == "openstack":
        topology_data = {
            "links": [link.model_dump() for link in slice_in.links],
            "networks": [net.model_dump() for net in slice_in.networks]
        }
    else:
        topology_data = [link.model_dump() for link in slice_in.links]

    # SLICE_ADMIN/SYSTEM_ADMIN: el slice queda como Borrador (DRAFT) hasta que se despliegue
    # explícitamente vía POST /{id}/deploy. STUDENT: sigue el flujo de aprobación existente.
    is_admin = user.role in ["SLICE_ADMIN", "SYSTEM_ADMIN"]
    slice_status = "DRAFT" if is_admin else "PENDING_APPROVAL"
    new_slice = models.Slice(
        user_id=user.id,
        name=slice_in.name,
        topology=topology_data,
        iaas_target=slice_in.iaas_target,
        status=slice_status
    )
    db.add(new_slice)
    await db.flush()

    vm_status = "DRAFT" if is_admin else "PENDING_APPROVAL"
    vm_records = await _build_vms(slice_in, user, new_slice.id, vm_status, db)

    # Nota: la creación de tareas CREATE_VM y el trigger de Placement ya no
    # ocurren aquí. Para SLICE_ADMIN/SYSTEM_ADMIN el slice queda en DRAFT y
    # se activa explícitamente vía POST /{id}/deploy (linux u openstack).

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
# PUT /slices/{id} — Editar la topología de un Borrador (SLICE_ADMIN/SYSTEM_ADMIN)
# ---------------------------------------------------------------------------
# Solo permitido mientras el slice está en DRAFT. Reemplaza nombre, destino,
# topología (links/networks) y VMs por completo: borra las VMs actuales
# (en DRAFT no tienen interfaces/tareas reales aún) y las reconstruye con
# _build_vms, igual que en la creación.
# ---------------------------------------------------------------------------
@router.put("/{id}", response_model=schemas.SliceCreateResponse)
async def update_slice(
    id: int,
    slice_in: schemas.SliceCreate,
    x_user_role: str = Header(...),
    x_user_id: int = Header(...),
    db: AsyncSession = Depends(get_db)
):
    user = await get_current_user(x_user_role, x_user_id, db)
    if user.role not in ["SLICE_ADMIN", "SYSTEM_ADMIN"]:
        raise HTTPException(status_code=403, detail="Only SLICE_ADMIN/SYSTEM_ADMIN can edit slices")

    result = await db.execute(
        select(models.Slice).options(selectinload(models.Slice.vms)).where(models.Slice.id == id)
    )
    slice_obj = result.scalar_one_or_none()
    if not slice_obj:
        raise HTTPException(status_code=404, detail="Slice not found")

    if user.role == "SLICE_ADMIN" and slice_obj.user_id != user.id:
        student_res = await db.execute(select(models.User).where(models.User.id == slice_obj.user_id))
        student = student_res.scalar_one_or_none()
        if not student or student.admin_id != user.id:
            raise HTTPException(status_code=403, detail="Not authorized")

    if slice_obj.status != "DRAFT":
        raise HTTPException(status_code=409, detail="Only slices in DRAFT state can be edited")

    if slice_in.iaas_target == "linux":
        async with httpx.AsyncClient() as client:
            for vm in slice_in.vms:
                try:
                    res = await client.get(f"{IMAGE_MANAGER_URL}/images/{vm.base_image}/validate")
                    if res.status_code != 200:
                        raise HTTPException(status_code=400, detail=f"Image {vm.base_image} invalid or not found")
                except httpx.RequestError:
                    raise HTTPException(status_code=503, detail="Image Manager service unavailable")

    if slice_in.iaas_target == "openstack":
        topology_data = {
            "links": [link.model_dump() for link in slice_in.links],
            "networks": [net.model_dump() for net in slice_in.networks]
        }
    else:
        topology_data = [link.model_dump() for link in slice_in.links]

    # Reemplazo completo de VMs: en DRAFT no existen interfaces/tareas reales aún.
    for vm in list(slice_obj.vms):
        await db.delete(vm)
    await db.flush()

    slice_obj.name = slice_in.name
    slice_obj.iaas_target = slice_in.iaas_target
    slice_obj.topology = topology_data
    await db.flush()

    vm_records = await _build_vms(slice_in, user, slice_obj.id, "DRAFT", db)

    await db.commit()
    await db.refresh(slice_obj)

    vms_response = [
        schemas.SliceResponseVM(id=vm_records[v].id, name=vm_records[v].name, status=vm_records[v].status)
        for v in vm_records
    ]
    return schemas.SliceCreateResponse(
        slice_id=slice_obj.id,
        name=slice_obj.name,
        status=slice_obj.status,
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
        student_ids.append(user.id)
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
            iaas_target=s.iaas_target,
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
        
    if user.role == "SLICE_ADMIN" and slice_obj.user_id != user.id:
        student_res = await db.execute(select(models.User).where(models.User.id == slice_obj.user_id))
        student = student_res.scalar_one_or_none()
        if not student or student.admin_id != user.id:
            raise HTTPException(status_code=403, detail="Not authorized")

    worker_ids = {vm.worker_id for vm in slice_obj.vms if vm.worker_id is not None}
    worker_names = {}
    if worker_ids:
        workers_res = await db.execute(
            text("SELECT id, hostname FROM workers WHERE id = ANY(:ids)"),
            {"ids": list(worker_ids)}
        )
        worker_names = {row.id: row.hostname for row in workers_res}

    OPENSTACK_DRIVER_URL = os.getenv("OPENSTACK_DRIVER_URL", "http://openstack-driver:8089")
    image_names = {}

    vms = []
    async with httpx.AsyncClient(timeout=5.0) as client:
        if slice_obj.iaas_target == "openstack":
            try:
                res = await client.get(f"{OPENSTACK_DRIVER_URL}/v1/images")
                if res.status_code == 200:
                    image_names = {img["id"]: img["name"] for img in res.json().get("images", [])}
            except Exception:
                pass

        for vm in slice_obj.vms:
            interfaces = []
            for iface in vm.interfaces:
                net_res = await db.execute(select(models.Network).where(models.Network.id == iface.network_id))
                net = net_res.scalar_one_or_none()
                interfaces.append(schemas.VmInterfaceDetail(
                    interface_name=iface.interface_name,
                    tap_name=iface.tap_name,
                    vlan_inner=net.vlan_inner if net else 0,
                    bridge_name=iface.bridge_name or (f"br-sl-{slice_obj.id}" if net else "br-inet")
                ))
                
            vnc_url = vm.vnc_url
            if slice_obj.iaas_target == "openstack" and vm.instance_path:
                try:
                    res = await client.get(f"{OPENSTACK_DRIVER_URL}/v1/vms/{vm.instance_path}/vnc")
                    if res.status_code == 200:
                        vnc_url = res.json().get("vnc_url", vm.vnc_url)
                except Exception:
                    pass
                
            vms.append(schemas.VMDetail(
                id=vm.id,
                name=vm.name,
                worker_id=vm.worker_id,
                worker_name=worker_names.get(vm.worker_id),
                status=vm.status,
                process_id=vm.process_id,
                vnc_port=vm.vnc_port,
                vnc_url=vnc_url,
                base_image=image_names.get(vm.base_image, vm.base_image),
                ram=vm.ram,
                vcpu=vm.vcpu,
                disk=vm.disk,
                interfaces=interfaces
            ))

    if slice_obj.iaas_target == "openstack":
        links = (slice_obj.topology or {}).get("links", [])
    else:
        links = slice_obj.topology or []

    return schemas.SliceDetailResponse(
        id=slice_obj.id,
        name=slice_obj.name,
        status=slice_obj.status,
        vlan_slice=slice_obj.vlan_slice,
        vms=vms,
        links=links
    )

# ---------------------------------------------------------------------------
# GET /slices/{id}/export — Exportar la topología lógica de un slice
# ---------------------------------------------------------------------------
# Devuelve exactamente la forma de schemas.SliceCreate (name, iaas_target,
# vms, links, networks), de modo que el archivo descargado se pueda volver a
# enviar tal cual a POST /slices/ (con un nombre distinto) para clonarlo.
# ---------------------------------------------------------------------------
@router.get("/{id}/export", response_model=schemas.SliceCreate)
async def export_slice(
    id: int,
    x_user_role: str = Header(...),
    x_user_id: int = Header(...),
    db: AsyncSession = Depends(get_db)
):
    user = await get_current_user(x_user_role, x_user_id, db)
    if user.role not in ["SLICE_ADMIN", "SYSTEM_ADMIN"]:
        raise HTTPException(status_code=403, detail="Only SLICE_ADMIN/SYSTEM_ADMIN can export topologies")

    result = await db.execute(
        select(models.Slice).options(selectinload(models.Slice.vms)).where(models.Slice.id == id)
    )
    slice_obj = result.scalar_one_or_none()
    if not slice_obj:
        raise HTTPException(status_code=404, detail="Slice not found")

    if user.role == "SLICE_ADMIN" and slice_obj.user_id != user.id:
        student_res = await db.execute(select(models.User).where(models.User.id == slice_obj.user_id))
        student = student_res.scalar_one_or_none()
        if not student or student.admin_id != user.id:
            raise HTTPException(status_code=403, detail="Not authorized")

    if slice_obj.iaas_target == "openstack":
        topology = slice_obj.topology or {}
        links = topology.get("links", [])
        networks = topology.get("networks", [])
    else:
        links = slice_obj.topology or []
        networks = []

    return schemas.SliceCreate(
        name=slice_obj.name,
        iaas_target=slice_obj.iaas_target,
        vms=[
            schemas.VMSchema(name=vm.name, base_image=vm.base_image, flavor_id=vm.flavor_id, flavor=vm.flavor)
            for vm in slice_obj.vms
        ],
        links=[schemas.LinkSchema(**l) for l in links],
        networks=[schemas.NetworkSchema(**n) for n in networks],
    )

# ---------------------------------------------------------------------------
# POST /slices/{id}/deploy — Despliegue bajo demanda de un slice en Borrador
# ---------------------------------------------------------------------------
# Solo SLICE_ADMIN/SYSTEM_ADMIN. Transiciona DRAFT -> ACTIVE ejecutando el
# mismo flujo de activación que /approve (placement + networking para linux,
# creación de tareas CREATE_VM + placement para openstack).
# ---------------------------------------------------------------------------
@router.post("/{id}/deploy", response_model=schemas.MessageResponse)
async def deploy_slice(
    id: int,
    x_user_role: str = Header(...),
    x_user_id: int = Header(...),
    db: AsyncSession = Depends(get_db)
):
    user = await get_current_user(x_user_role, x_user_id, db)
    if user.role not in ["SLICE_ADMIN", "SYSTEM_ADMIN"]:
        raise HTTPException(status_code=403, detail="Only SLICE_ADMIN/SYSTEM_ADMIN can deploy slices")

    result = await db.execute(
        select(models.Slice).options(selectinload(models.Slice.vms)).where(models.Slice.id == id)
    )
    slice_obj = result.scalar_one_or_none()
    if not slice_obj:
        raise HTTPException(status_code=404, detail="Slice not found")

    if user.role == "SLICE_ADMIN" and slice_obj.user_id != user.id:
        student_res = await db.execute(select(models.User).where(models.User.id == slice_obj.user_id))
        student = student_res.scalar_one_or_none()
        if not student or student.admin_id != user.id:
            raise HTTPException(status_code=403, detail="Not authorized")

    if slice_obj.status != "DRAFT":
        raise HTTPException(status_code=409, detail="Slice is not in DRAFT state")

    if slice_obj.iaas_target == "openstack":
        tasks_created, activation_message = await _activate_openstack_slice(slice_obj, db)
    else:
        tasks_created, activation_message = await _activate_linux_slice(slice_obj, db)

    return schemas.MessageResponse(
        slice_id=slice_obj.id,
        status="ACTIVE",
        message=f"Slice desplegado. {activation_message}",
        tasks_created=tasks_created
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

    if slice_obj.user_id != user.id:
        student_res = await db.execute(select(models.User).where(models.User.id == slice_obj.user_id))
        student = student_res.scalar_one_or_none()
        if not student or student.admin_id != user.id:
            if user.role != "SYSTEM_ADMIN":
                raise HTTPException(status_code=403, detail="Not authorized to approve this student's slice")

    # --- FLUJO OPENSTACK DIRECTO ---
    if slice_obj.iaas_target == "openstack":
        tasks_created, activation_message = await _activate_openstack_slice(slice_obj, db)
        return schemas.MessageResponse(
            slice_id=slice_obj.id,
            status="ACTIVE",
            message=f"Slice de OpenStack aprobado. {activation_message}",
            tasks_created=tasks_created
        )

    tasks_created, activation_message = await _activate_linux_slice(slice_obj, db)

    return schemas.MessageResponse(
        slice_id=slice_obj.id,
        status="ACTIVE",
        message=f"Slice aprobado. {activation_message}",
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
    result = await db.execute(select(models.Slice).options(selectinload(models.Slice.vms), selectinload(models.Slice.networks)).where(models.Slice.id == id))
    slice_obj = result.scalar_one_or_none()
    if not slice_obj:
        raise HTTPException(status_code=404, detail="Slice not found")

    if user.role == "STUDENT" and slice_obj.user_id != user.id:
        raise HTTPException(status_code=403, detail="Not authorized")

    vms_count = len(slice_obj.vms)
    networks_count = len(slice_obj.networks)
    vlan_freed = slice_obj.vlan_slice

    # --- FLUJO DE BORRADO DE OPENSTACK ---
    if slice_obj.iaas_target == "openstack":
        OPENSTACK_DRIVER_URL = os.getenv("OPENSTACK_DRIVER_URL", "http://openstack-driver:8089")
        async with httpx.AsyncClient(timeout=120.0) as client:
            try:
                await client.post(f"{OPENSTACK_DRIVER_URL}/v1/vms/delete", json={"slice_id": slice_obj.name})
            except httpx.RequestError:
                pass  # Best-effort deletion
                
        await db.delete(slice_obj)
        await db.commit()
        
        return {
            "slice_id": id,
            "status": "DELETED",
            "cleanup": {
                "vms_terminated": vms_count,
                "networks_released": 0,
                "vlan_slice_freed": 0
            }
        }

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
                    "mac_address": iface.mac_address,
                    "bridge_name": iface.bridge_name or (f"br-sl-{id}" if net else "br-inet"),
                    "is_remote": net.is_remote if net else False
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
