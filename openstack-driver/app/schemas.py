from pydantic import BaseModel, Field
from typing import List, Optional

# --- CREATE SCHEMAS ---

class VmCreatePayload(BaseModel):
    name: str
    image: str
    flavor: str
    networks: List[str]
    host: Optional[str] = None

class NetworkCreatePayload(BaseModel):
    name: str
    cidr: Optional[str] = None
    is_provider: bool = False

class CreateSliceRequest(BaseModel):
    slice_id: str
    vms: List[VmCreatePayload]
    networks: List[NetworkCreatePayload]

class VmDeployDetail(BaseModel):
    name: str
    server_id: str
    status: str
    vnc_url: Optional[str] = None

class CreateSliceResponse(BaseModel):
    slice_id: str
    status: str  # "READY", "FAILED"
    project_id: str
    vms: List[VmDeployDetail] = []
    message: str

# --- DELETE SCHEMAS ---

class DeleteSliceRequest(BaseModel):
    slice_id: str

class DeleteSliceResponse(BaseModel):
    slice_id: str
    status: str  # "DELETED", "FAILED"
    message: str
