from pydantic import BaseModel
from typing import List

class InterfaceRequest(BaseModel):
    network_name: str
    interface_name: str

class VmRequest(BaseModel):
    vm_id: int
    interfaces: List[InterfaceRequest]

class NetworkRequest(BaseModel):
    name: str

class AllocateRequest(BaseModel):
    slice_id: int
    networks: List[NetworkRequest]
    vms: List[VmRequest]

class ReleaseRequest(BaseModel):
    slice_id: int
