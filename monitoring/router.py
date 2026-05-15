from fastapi import APIRouter, Depends, Header, HTTPException
from sqlalchemy.ext.asyncio import AsyncSession
from typing import Optional
from database import get_db
from schemas import WorkerListResponse, WorkerResponse, HealthResponse
from service import get_workers_for_user, get_worker_by_id_for_user
import datetime
from ssh_client import SSH_ENABLED

router = APIRouter()

@router.get("/monitoring/workers", response_model=WorkerListResponse)
async def list_workers(
    x_user_role: str = Header(default="STUDENT", alias="X-User-Role"),
    x_user_id: Optional[str] = Header(default=None, alias="X-User-Id"),
    session: AsyncSession = Depends(get_db)
):
    uid = int(x_user_id) if x_user_id and x_user_id.isdigit() else None
    
    # Check if role requires ID but ID is missing
    if x_user_role in ["STUDENT", "SLICE_ADMIN"] and uid is None:
        return {"workers": []}

    workers = await get_workers_for_user(session, user_role=x_user_role, user_id=uid)
    return {"workers": workers}

@router.get("/monitoring/workers/{id}", response_model=WorkerResponse)
async def get_worker(
    id: int,
    x_user_role: str = Header(default="STUDENT", alias="X-User-Role"),
    x_user_id: Optional[str] = Header(default=None, alias="X-User-Id"),
    session: AsyncSession = Depends(get_db)
):
    uid = int(x_user_id) if x_user_id and x_user_id.isdigit() else None
    
    worker = await get_worker_by_id_for_user(session, worker_id=id, user_role=x_user_role, user_id=uid)
    if not worker:
        raise HTTPException(status_code=404, detail="Worker not found or access denied")
        
    return worker

@router.get("/health", response_model=HealthResponse)
async def health_check():
    return {
        "status": "ok",
        "ssh_enabled": SSH_ENABLED,
        "last_poll": datetime.datetime.now(datetime.timezone.utc).replace(microsecond=0).isoformat()
    }
