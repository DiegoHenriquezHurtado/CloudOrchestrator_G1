from pydantic import BaseModel
from typing import List, Optional, Dict, Any


# --- Request from Dispatcher ---

class VmPayload(BaseModel):
    id: int
    name: str
    base_image: str
    ram: int
    vcpu: int
    instance_path: str

class SlicePayload(BaseModel):
    id: int
    vlan_slice: int

class InterfacePayload(BaseModel):
    interface_name: str
    tap_name: str
    vlan_inner: int
    ip_address: str
    mac_address: str
    bridge_name: str
    is_remote: bool
    internet_access: bool = False

class ExecuteRequest(BaseModel):
    task_id: int
    task_type: str  # CREATE_VM, DELETE_VM, APPLY_SECURITY
    worker_ip: str
    vm: VmPayload
    slice: SlicePayload
    interfaces: List[InterfacePayload] = []
    # DELETE_VM extras
    process_id: Optional[int] = None
    # APPLY_SECURITY extras
    setup_flows: Optional[List[Dict[str, str]]] = None
    policy_flows: Optional[List[Dict[str, str]]] = None


# --- Response to Dispatcher ---

class ExecuteSuccessResponse(BaseModel):
    task_id: int
    status: str  # "READY"
    process_id: Optional[int] = None
    vnc_port: Optional[int] = None
    commands_executed: List[str] = []

class ExecuteFailureResponse(BaseModel):
    task_id: int
    status: str  # "FAILED"
    error_msg: str
    rollback_actions: List[str] = []
