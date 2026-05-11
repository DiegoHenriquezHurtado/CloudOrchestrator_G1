from pydantic import BaseModel
from typing import List, Optional

class VmInterfaceCreate(BaseModel):
    network_name: str
    interface_name: str

class VmCreate(BaseModel):
    name: str
    base_image: str
    ram: int
    vcpu: int
    interfaces: List[VmInterfaceCreate]

class TopologyCreate(BaseModel):
    name: str
    networks: List[str]
    vms: List[VmCreate]

class VmInterfaceResponse(BaseModel):
    id: int
    mac_address: Optional[str]
    ip_address: Optional[str]
    interface_name: Optional[str]
    tap_name: Optional[str]
    class Config:
        from_attributes = True

class VirtualMachineResponse(BaseModel):
    id: int
    name: str
    base_image: str
    ram: int
    vcpu: int
    status: str
    vnc_port: Optional[int]
    process_id: Optional[int]
    class Config:
        from_attributes = True

class NetworkResponse(BaseModel):
    id: int
    vlan_id: Optional[int]
    subnet_cidr: Optional[str]
    class Config:
        from_attributes = True

class SliceResponse(BaseModel):
    id: int
    name: str
    status: str
    user_id: int
    class Config:
        from_attributes = True
