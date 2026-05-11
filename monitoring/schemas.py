from pydantic import BaseModel
from typing import Optional
from datetime import datetime

class WorkerResponse(BaseModel):
    id: int
    hostname: str
    ip_management: str
    total_ram: int
    total_cpu: int
    current_cpu_load: float
    current_ram_available: int
    status: str
    updated_at: Optional[datetime]

    class Config:
        from_attributes = True

class HealthResponse(BaseModel):
    status: str
