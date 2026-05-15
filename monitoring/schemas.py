from pydantic import BaseModel
from typing import List, Optional
import datetime

class WorkerBase(BaseModel):
    hostname: str
    ip_management: str
    total_ram: int
    total_cpu: int
    current_cpu_load: float
    current_ram_available: int
    status: str
    updated_at: datetime.datetime

class WorkerResponse(WorkerBase):
    id: int

    class Config:
        from_attributes = True

class WorkerListResponse(BaseModel):
    workers: List[WorkerResponse]

class HealthResponse(BaseModel):
    status: str
    ssh_enabled: bool
    last_poll: str
