import os
import httpx
from fastapi import FastAPI, Depends, HTTPException, status
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select
from typing import List

from database import get_db
from models import User, Slice, VirtualMachine, Network, VmInterface, Task
from schemas import TopologyCreate, SliceResponse
from dependencies import get_current_student, get_current_slice_admin, get_current_user

app = FastAPI(title="Slice Manager Module", version="1.0")

IMAGE_MANAGER_URL = os.getenv("IMAGE_MANAGER_URL", "http://image-manager:8083")
NETWORKING_URL = os.getenv("NETWORKING_URL", "http://networking:8085")

@app.post("/slices/", response_model=SliceResponse)
async def create_slice(topology: TopologyCreate, user: User = Depends(get_current_student), db: AsyncSession = Depends(get_db)):
    # 1. Validate images with Image Manager
    async with httpx.AsyncClient() as client:
        for vm in topology.vms:
            try:
                resp = await client.get(f"{IMAGE_MANAGER_URL}/images/{vm.base_image}/validate")
                if resp.status_code != 200:
                    raise HTTPException(status_code=400, detail=f"Image {vm.base_image} validation failed")
            except httpx.RequestError:
                raise HTTPException(status_code=503, detail="Image Manager is unavailable")
                
    # 2. Create preliminary slice
    new_slice = Slice(user_id=user.id, name=topology.name, status='PENDING_APPROVAL')
    db.add(new_slice)
    await db.flush()
    
    # 3. Create VMs
    created_vms = []
    for vm_req in topology.vms:
        new_vm = VirtualMachine(
            slice_id=new_slice.id,
            name=vm_req.name,
            base_image=vm_req.base_image,
            ram=vm_req.ram,
            vcpu=vm_req.vcpu,
            status='PENDING_APPROVAL'
        )
        db.add(new_vm)
        created_vms.append((new_vm, vm_req))
        
    await db.flush()
    
    # 4. Call Networking
    networking_payload = {
        "slice_id": new_slice.id,
        "networks": [{"name": net_name} for net_name in topology.networks],
        "vms": []
    }
    
    for new_vm, vm_req in created_vms:
        networking_payload["vms"].append({
            "vm_id": new_vm.id,
            "interfaces": [{"network_name": iface.network_name, "interface_name": iface.interface_name} for iface in vm_req.interfaces]
        })
        
    async with httpx.AsyncClient() as client:
        try:
            resp = await client.post(f"{NETWORKING_URL}/networking/allocate", json=networking_payload)
            if resp.status_code != 200:
                raise HTTPException(status_code=400, detail=f"Networking allocation failed: {resp.text}")
        except httpx.RequestError:
            raise HTTPException(status_code=503, detail="Networking module is unavailable")
            
    await db.commit()
    return new_slice

@app.get("/slices/")
async def list_slices(user: User = Depends(get_current_user), db: AsyncSession = Depends(get_db)):
    if user.role == "STUDENT":
        result = await db.execute(select(Slice).where(Slice.user_id == user.id))
    elif user.role in ["SLICE_ADMIN", "SYSTEM_ADMIN"]:
        if user.role == "SYSTEM_ADMIN":
            result = await db.execute(select(Slice))
        else:
            result = await db.execute(
                select(Slice).join(User, Slice.user_id == User.id).where(User.admin_id == user.id)
            )
    else:
        raise HTTPException(status_code=403, detail="Invalid role")
        
    return result.scalars().all()

@app.get("/slices/{id}")
async def get_slice(id: int, user: User = Depends(get_current_user), db: AsyncSession = Depends(get_db)):
    result = await db.execute(select(Slice).where(Slice.id == id))
    slice_obj = result.scalars().first()
    if not slice_obj:
        raise HTTPException(status_code=404, detail="Slice not found")
        
    if user.role == "STUDENT" and slice_obj.user_id != user.id:
        raise HTTPException(status_code=403, detail="Not your slice")
    if user.role == "SLICE_ADMIN":
        student_res = await db.execute(select(User).where(User.id == slice_obj.user_id))
        student = student_res.scalars().first()
        if student and student.admin_id != user.id:
            raise HTTPException(status_code=403, detail="Not your student's slice")
            
    vms_res = await db.execute(select(VirtualMachine).where(VirtualMachine.slice_id == id))
    vms = vms_res.scalars().all()
    
    vm_data = []
    for vm in vms:
        ifaces_res = await db.execute(select(VmInterface).where(VmInterface.vm_id == vm.id))
        ifaces = ifaces_res.scalars().all()
        vm_data.append({
            "id": vm.id,
            "name": vm.name,
            "status": vm.status,
            "base_image": vm.base_image,
            "vnc_port": vm.vnc_port,
            "process_id": vm.process_id,
            "worker_id": vm.worker_id,
            "interfaces": [{"ip_address": iface.ip_address, "mac_address": iface.mac_address, "interface_name": iface.interface_name} for iface in ifaces]
        })
        
    return {
        "id": slice_obj.id,
        "name": slice_obj.name,
        "status": slice_obj.status,
        "user_id": slice_obj.user_id,
        "vms": vm_data
    }

@app.post("/slices/{id}/approve")
async def approve_slice(id: int, user: User = Depends(get_current_slice_admin), db: AsyncSession = Depends(get_db)):
    result = await db.execute(select(Slice).where(Slice.id == id))
    slice_obj = result.scalars().first()
    if not slice_obj:
        raise HTTPException(status_code=404, detail="Slice not found")
        
    if slice_obj.status != 'PENDING_APPROVAL':
        raise HTTPException(status_code=400, detail="Slice is not in PENDING_APPROVAL status")
        
    student_res = await db.execute(select(User).where(User.id == slice_obj.user_id))
    student = student_res.scalars().first()
    if user.role == "SLICE_ADMIN" and student and student.admin_id != user.id:
        raise HTTPException(status_code=403, detail="Not your student's slice")
        
    slice_obj.status = 'PENDING'
    
    vms_res = await db.execute(select(VirtualMachine).where(VirtualMachine.slice_id == id))
    vms = vms_res.scalars().all()
    for vm in vms:
        vm.status = 'PENDING'
        
        ifaces_res = await db.execute(select(VmInterface).where(VmInterface.vm_id == vm.id))
        ifaces = ifaces_res.scalars().all()
        
        interfaces_payload = []
        for iface in ifaces:
            net_res = await db.execute(select(Network).where(Network.id == iface.network_id))
            net = net_res.scalars().first()
            interfaces_payload.append({
                "network_id": iface.network_id,
                "mac_address": iface.mac_address,
                "ip_address": iface.ip_address,
                "interface_name": iface.interface_name,
                "tap_name": iface.tap_name,
                "vlan_id": net.vlan_id if net else None
            })
        
        payload = {
            "vm_id": vm.id,
            "name": vm.name,
            "base_image": vm.base_image,
            "ram": vm.ram,
            "vcpu": vm.vcpu,
            "interfaces": interfaces_payload
        }
        
        new_task = Task(
            slice_id=slice_obj.id,
            vm_id=vm.id,
            task_type='CREATE_VM',
            status='PENDING',
            payload=payload
        )
        db.add(new_task)
        
    await db.commit()
    return {"status": "success", "message": "Slice approved and tasks created"}

@app.post("/slices/{id}/reject")
async def reject_slice(id: int, user: User = Depends(get_current_slice_admin), db: AsyncSession = Depends(get_db)):
    result = await db.execute(select(Slice).where(Slice.id == id))
    slice_obj = result.scalars().first()
    if not slice_obj:
        raise HTTPException(status_code=404, detail="Slice not found")
        
    if slice_obj.status != 'PENDING_APPROVAL':
        raise HTTPException(status_code=400, detail="Slice is not in PENDING_APPROVAL status")
        
    slice_obj.status = 'FAILED'
    
    # Optional: trigger networking release for the slice since it was rejected
    async with httpx.AsyncClient() as client:
        try:
            await client.post(f"{NETWORKING_URL}/networking/release", json={"slice_id": id})
        except httpx.RequestError:
            pass
            
    await db.commit()
    return {"status": "success", "message": "Slice rejected"}

@app.delete("/slices/{id}")
async def delete_slice(id: int, user: User = Depends(get_current_user), db: AsyncSession = Depends(get_db)):
    result = await db.execute(select(Slice).where(Slice.id == id))
    slice_obj = result.scalars().first()
    if not slice_obj:
        raise HTTPException(status_code=404, detail="Slice not found")
        
    if user.role == "STUDENT" and slice_obj.user_id != user.id:
        raise HTTPException(status_code=403, detail="Not your slice")
        
    vms_res = await db.execute(select(VirtualMachine).where(VirtualMachine.slice_id == id))
    vms = vms_res.scalars().all()
    
    for vm in vms:
        new_task = Task(
            slice_id=slice_obj.id,
            vm_id=vm.id,
            task_type='DELETE_VM',
            status='PENDING',
            payload={"vm_id": vm.id, "worker_id": vm.worker_id, "process_id": vm.process_id, "instance_path": vm.instance_path}
        )
        db.add(new_task)
        
    slice_obj.status = 'TERMINATING'
    
    await db.commit()
    return {"status": "success", "message": "Cleanup tasks created. Slice is terminating."}
