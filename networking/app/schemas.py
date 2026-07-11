from pydantic import BaseModel
from typing import List, Dict, Optional

class LinkRequest(BaseModel):
    link_name: str
    vm_a_id: int
    iface_a: str
    vm_b_id: int
    iface_b: str

class AllocateRequest(BaseModel):
    slice_id: int
    placement_map: Dict[str, int]
    links: List[LinkRequest]

class InterfaceDetail(BaseModel):
    vm_id: int
    interface_name: str
    tap_name: str
    mac_address: str
    bridge_name: Optional[str] = None
    worker_id: Optional[int] = None

class NetworkDetail(BaseModel):
    network_id: Optional[int] = None
    id: Optional[int] = None
    link_name: Optional[str] = None
    vlan_inner: int
    is_remote: bool
    interfaces: List[InterfaceDetail]

class AllocateResponse(BaseModel):
    slice_id: int
    vlan_slice: int
    bridge_name: str
    networks: List[NetworkDetail]

class ReleaseRequest(BaseModel):
    slice_id: int

class VlanAvailableResponse(BaseModel):
    total: int
    available: int
    used: int

class SliceNetworkResponse(BaseModel):
    slice_id: int
    vlan_slice: int
    bridge_name: str
    networks: List[NetworkDetail]

class OvsWorkerCommand(BaseModel):
    worker_id: int
    commands: List[str]

class OvsCommandResponse(BaseModel):
    slice_id: int
    vlan_slice: int
    bridge_name: str
    workers: List[OvsWorkerCommand]
