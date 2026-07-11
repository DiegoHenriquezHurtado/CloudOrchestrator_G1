import asyncio
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.future import select
import datetime
from typing import List, Optional

from models import Worker, User, Slice, VirtualMachine
from ssh_client import get_worker_metrics, SSH_ENABLED

async def update_all_workers_metrics(session: AsyncSession):
    # Fetch only linux workers
    result = await session.execute(select(Worker).where(Worker.cluster_type == 'linux'))
    workers = result.scalars().all()

    for worker in workers:
        if not SSH_ENABLED:
            continue
            
        metrics = await get_worker_metrics(worker.ip_management)
        
        if metrics:
            if "total_ram" in metrics and worker.total_ram == 0:
                worker.total_ram = metrics["total_ram"]
            if "total_cpu" in metrics and worker.total_cpu == 0:
                worker.total_cpu = metrics["total_cpu"]
            
            if "current_cpu_load" in metrics:
                worker.current_cpu_load = metrics["current_cpu_load"]
            if "current_ram_available" in metrics:
                worker.current_ram_available = metrics["current_ram_available"]
            
            worker.status = metrics.get("status", "DOWN")
            worker.updated_at = datetime.datetime.now(datetime.timezone.utc).replace(tzinfo=None)
            
    await session.commit()

async def get_workers_for_user(session: AsyncSession, user_role: str, user_id: Optional[int] = None) -> List[Worker]:
    if user_role == "SYSTEM_ADMIN":
        result = await session.execute(select(Worker).order_by(Worker.id))
        return list(result.scalars().all())
        
    if not user_id:
        # Si no hay ID pero el rol requiere filtrar, devolvemos vacio temporalmente o lanzamos error.
        # Asumimos que gateway siempre inyecta X-User-Id si esta autenticado.
        return []

    if user_role == "SLICE_ADMIN":
        # SLICE_ADMIN ve workers de las VMs de sus alumnos (User.admin_id == user_id)
        query = select(Worker).distinct().join(VirtualMachine, VirtualMachine.worker_id == Worker.id)\
            .join(Slice, VirtualMachine.slice_id == Slice.id)\
            .join(User, Slice.user_id == User.id)\
            .where(User.admin_id == user_id).order_by(Worker.id)
        result = await session.execute(query)
        return list(result.scalars().all())

    if user_role == "STUDENT":
        # STUDENT ve workers de sus propias VMs (Slice.user_id == user_id)
        query = select(Worker).distinct().join(VirtualMachine, VirtualMachine.worker_id == Worker.id)\
            .join(Slice, VirtualMachine.slice_id == Slice.id)\
            .where(Slice.user_id == user_id).order_by(Worker.id)
        result = await session.execute(query)
        return list(result.scalars().all())

    return []

async def get_worker_by_id_for_user(session: AsyncSession, worker_id: int, user_role: str, user_id: Optional[int] = None) -> Optional[Worker]:
    workers = await get_workers_for_user(session, user_role, user_id)
    for w in workers:
        if w.id == worker_id:
            return w
    return None
