from pydantic import BaseModel, Field
from typing import List, Optional

class VMSchema(BaseModel):
    name: str
    base_image: str
    ram: int
    vcpu: int

class LinkSchema(BaseModel):
    vm_a: str
    iface_a: str
    vm_b: str
    iface_b: str

class SliceCreate(BaseModel):
    name: str
    vms: List[VMSchema]
    links: List[LinkSchema] = Field(default_factory=list)

class SliceResponseVM(BaseModel):
    id: int
    name: str
    status: str

    class Config:
        from_attributes = True

class SliceCreateResponse(BaseModel):
    slice_id: int
    name: str
    status: str
    vms: List[SliceResponseVM]
    links_count: int

class SliceListResponseItem(BaseModel):
    id: int
    name: str
    status: str
    vms_count: int
    created_at: str

    class Config:
        from_attributes = True

class SliceListResponse(BaseModel):
    slices: List[SliceListResponseItem]

class VmInterfaceDetail(BaseModel):
    interface_name: Optional[str]
    ip_address: Optional[str]
    tap_name: Optional[str]
    vlan_inner: Optional[int]

    class Config:
        from_attributes = True

class VMDetail(BaseModel):
    id: int
    name: str
    worker_id: Optional[int]
    status: str
    process_id: Optional[int]
    vnc_port: Optional[int]
    interfaces: List[VmInterfaceDetail]

    class Config:
        from_attributes = True

class SliceDetailResponse(BaseModel):
    id: int
    name: str
    status: str
    vlan_slice: Optional[int]
    vms: List[VMDetail]

    class Config:
        from_attributes = True

class MessageResponse(BaseModel):
    slice_id: int
    status: str
    message: str
    tasks_created: Optional[int] = None
