from pydantic import BaseModel
from typing import List, Dict, Optional

class LinkRequest(BaseModel):
    link_name: str
    vm_a_id: int
    iface_a: str
    vm_b_id: int
    iface_b: str
    internet_access: Optional[bool] = False

class AllocateRequest(BaseModel):
    slice_id: int
    placement_map: Dict[str, int]
    links: List[LinkRequest]

class InterfaceDetail(BaseModel):
    vm_id: int
    interface_name: str
    tap_name: str
    ip_address: str
    mac_address: str
    worker_id: Optional[int] = None

class NetworkDetail(BaseModel):
    network_id: Optional[int] = None
    id: Optional[int] = None
    link_name: Optional[str] = None
    vlan_inner: int
    subnet_cidr: str
    is_remote: bool
    internet_access: bool
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

class SecurityRuleCreate(BaseModel):
    slice_id: int
    src_vm_id: int
    dst_vm_id: int
    protocol: str = "any"
    port_min: Optional[int] = None
    port_max: Optional[int] = None
    action: str = "ALLOW"
    priority: int = 100

class SecurityRuleResponse(BaseModel):
    id: int
    slice_id: int
    src_vm_id: int
    dst_vm_id: int
    protocol: str
    port_min: Optional[int] = None
    port_max: Optional[int] = None
    action: str
    priority: int

class OvsFlow(BaseModel):
    bridge: str
    flow: str

class FlowResponse(BaseModel):
    slice_id: int
    setup_flows: List[OvsFlow]
    policy_flows: List[OvsFlow]

class NatNetworkCommand(BaseModel):
    network_id: int
    subnet_cidr: str
    commands: List[str]

class NatCommandResponse(BaseModel):
    slice_id: int
    nat_networks: List[NatNetworkCommand]
