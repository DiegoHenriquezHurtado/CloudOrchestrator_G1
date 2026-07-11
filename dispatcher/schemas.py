from pydantic import BaseModel
from typing import List, Optional, Dict, Any


# --- Dispatcher API responses ---

class DispatchedTask(BaseModel):
    task_id: int
    vm_id: int
    worker_ip: str
    status: str

class StatusResponse(BaseModel):
    polling_active: bool
    tasks_in_progress: int
    tasks_completed_last_hour: int
    tasks_failed_last_hour: int

class TriggerResponse(BaseModel):
    dispatched: List[DispatchedTask]
    errors: List[Dict[str, Any]] = []


# --- Payload sent to Driver (POST /driver/execute) ---

class DriverVmPayload(BaseModel):
    id: int
    name: str
    base_image: str
    ram: int
    vcpu: int
    instance_path: str

class DriverSlicePayload(BaseModel):
    id: int
    vlan_slice: int

class DriverInterfacePayload(BaseModel):
    interface_name: str
    tap_name: str
    vlan_inner: int
    mac_address: str
    bridge_name: Optional[str] = None
    is_remote: bool

class DriverExecuteRequest(BaseModel):
    task_id: int
    task_type: str
    worker_ip: str
    vm: DriverVmPayload
    slice: DriverSlicePayload
    interfaces: List[DriverInterfacePayload] = []
    # DELETE_VM extras
    process_id: Optional[int] = None
