from pydantic import BaseModel
from typing import List, Optional


class PlacementAssignment(BaseModel):
    task_id: int
    vm_id: int
    worker_id: int
    status: str


class PlacementSkip(BaseModel):
    task_id: int
    reason: str


class PlacementTriggerResponse(BaseModel):
    tasks_processed: int
    assignments: List[PlacementAssignment]
    skipped: List[PlacementSkip]


class PlacementStatusResponse(BaseModel):
    last_worker_id: int
    algorithm: str
    tasks_pending: Optional[int] = 0
    tasks_placement_ready: Optional[int] = 0
