from pydantic import BaseModel
from typing import List, Optional


# ------------------- ALLOCATE -------------------------------------------------

class InterfaceRequest(BaseModel):
    network_name: str
    interface_name: str

class VmRequest(BaseModel):
    vm_id: int
    worker_id: int          # Worker donde el Placement colocó esta VM
    interfaces: List[InterfaceRequest]

class NetworkRequest(BaseModel):
    name: str
    internet_access: bool = False

class AllocateRequest(BaseModel):
    slice_id: int
    networks: List[NetworkRequest]
    vms: List[VmRequest]

class ReleaseRequest(BaseModel):
    slice_id: int


# DETALLES DEL SLICE NETWORK (GET) 

class InterfaceDetail(BaseModel):
    vm_id: int
    worker_id: Optional[int]
    mac_address: str
    ip_address: str
    interface_name: str
    tap_name: str

class NetworkDetail(BaseModel):
    id: int
    vlan_slice: int
    vlan_inner: int
    subnet_cidr: str
    bridge_name: str
    is_remote: bool
    internet_access: bool
    interfaces: List[InterfaceDetail]

class SliceNetworkResponse(BaseModel):
    slice_id: int
    vlan_slice: int
    bridge_name: str
    networks: List[NetworkDetail]


# --------------- OVS COMMAND --------------------------------------------------

class OvsWorkerCommands(BaseModel):
    worker_id: int
    commands: List[str]     # lista de comandos ovs-vsctl listos para ejecutar

class SliceOvsResponse(BaseModel):
    slice_id: int
    vlan_slice: int
    bridge_name: str
    workers: List[OvsWorkerCommands]


# ------------------- SECURITY RULES ------------------------------------------

class SecurityRuleCreate(BaseModel):
    slice_id: int
    src_vm_id: int
    dst_vm_id: int
    protocol: str = "any"       # tcp, udp, icmp, any
    port_min: Optional[int] = None
    port_max: Optional[int] = None
    action: str = "ALLOW"       # ALLOW, DENY
    priority: int = 100

class SecurityRuleResponse(BaseModel):
    id: int
    slice_id: int
    src_vm_id: int
    dst_vm_id: int
    protocol: str
    port_min: Optional[int]
    port_max: Optional[int]
    action: str
    priority: int

class OvsFlow(BaseModel):
    bridge: str
    flow: str

class SliceFlowsResponse(BaseModel):
    slice_id: int
    setup_flows: List[OvsFlow]
    policy_flows: List[OvsFlow]


# ------------------- NAT -----------------------------------

class NatCommand(BaseModel):
    network_id: int
    subnet_cidr: str
    commands: List[str]

class SliceNatResponse(BaseModel):
    slice_id: int
    nat_networks: List[NatCommand]
