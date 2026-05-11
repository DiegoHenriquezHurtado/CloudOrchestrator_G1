import asyncio
from fastapi import FastAPI, Depends, HTTPException, status
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.future import select
from typing import List

from database import get_db, AsyncSessionLocal
from models import Worker, User, Slice, VirtualMachine
from schemas import WorkerResponse, HealthResponse
from auth import get_current_user
from ssh_service import update_all_workers
from contextlib import asynccontextmanager

@asynccontextmanager
async def lifespan(app: FastAPI):
    # Startup: Start the background polling task
    task = asyncio.create_task(polling_loop())
    yield
    # Shutdown: Cancel the task
    task.cancel()

async def polling_loop():
    while True:
        try:
            async with AsyncSessionLocal() as db:
                await update_all_workers(db)
        except Exception as e:
            print(f"Error in polling loop: {e}")
        await asyncio.sleep(60) # Poll every 60 seconds

app = FastAPI(title="Monitoring Service", lifespan=lifespan)

@app.get("/health", response_model=HealthResponse)
async def health_check():
    return {"status": "ok"}

@app.get("/monitoring/workers", response_model=List[WorkerResponse])
async def get_workers(db: AsyncSession = Depends(get_db), current_user: dict = Depends(get_current_user)):
    role = current_user.get("role")
    user_id = current_user.get("id")

    if role == "SYSTEM_ADMIN":
        # Can see all workers
        result = await db.execute(select(Worker))
        return result.scalars().all()
    elif role == "SLICE_ADMIN":
        # Can see workers where their students' VMs are running
        result = await db.execute(
            select(Worker).distinct()
            .join(VirtualMachine, Worker.id == VirtualMachine.worker_id)
            .join(Slice, VirtualMachine.slice_id == Slice.id)
            .join(User, Slice.user_id == User.id)
            .where(User.admin_id == user_id)
        )
        return result.scalars().all()
    else: # STUDENT
        # Can see workers where their own VMs are running
        result = await db.execute(
            select(Worker).distinct()
            .join(VirtualMachine, Worker.id == VirtualMachine.worker_id)
            .join(Slice, VirtualMachine.slice_id == Slice.id)
            .where(Slice.user_id == user_id)
        )
        return result.scalars().all()

@app.get("/monitoring/workers/{id}", response_model=WorkerResponse)
async def get_worker(id: int, db: AsyncSession = Depends(get_db), current_user: dict = Depends(get_current_user)):
    role = current_user.get("role")
    user_id = current_user.get("id")

    # Fetch the worker
    result = await db.execute(select(Worker).where(Worker.id == id))
    worker = result.scalar_first()
    
    if not worker:
        raise HTTPException(status_code=404, detail="Worker not found")

    # Visibility check
    if role == "SYSTEM_ADMIN":
        pass
    elif role == "SLICE_ADMIN":
        check = await db.execute(
            select(VirtualMachine).join(Slice).join(User)
            .where(VirtualMachine.worker_id == id)
            .where(User.admin_id == user_id)
            .limit(1)
        )
        if not check.scalar_first():
            raise HTTPException(status_code=403, detail="Not authorized to view this worker")
    else: # STUDENT
        check = await db.execute(
            select(VirtualMachine).join(Slice)
            .where(VirtualMachine.worker_id == id)
            .where(Slice.user_id == user_id)
            .limit(1)
        )
        if not check.scalar_first():
            raise HTTPException(status_code=403, detail="Not authorized to view this worker")

    return worker
