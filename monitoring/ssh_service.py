import os
import asyncssh
import asyncio
from sqlalchemy.ext.asyncio import AsyncSession
from models import Worker
import logging

logger = logging.getLogger(__name__)

SSH_ENABLED = os.getenv("SSH_ENABLED", "true").lower() == "true"
SSH_USER = "ubuntu"
SSH_PASSWORD = "ubuntu"

async def fetch_worker_metrics(worker: Worker):
    if not SSH_ENABLED:
        # Mock metrics for local development when SSH is disabled
        return {
            "total_ram": worker.total_ram if worker.total_ram > 0 else 16384,
            "total_cpu": worker.total_cpu if worker.total_cpu > 0 else 8,
            "current_cpu_load": 15.5,
            "current_ram_available": 8192,
            "status": "ALIVE"
        }

    try:
        async with asyncssh.connect(
            worker.ip_management, 
            username=SSH_USER, 
            password=SSH_PASSWORD,
            known_hosts=None
        ) as conn:
            # Check RAM
            ram_result = await conn.run("free -m | grep Mem | awk '{print $2, $7}'", check=True)
            # Check CPU Cores
            cpu_cores_result = await conn.run("nproc", check=True)
            # Check CPU Load
            cpu_load_result = await conn.run("top -bn1 | grep 'Cpu(s)' | awk '{print $2 + $4}'", check=True)
            
            try:
                ram_out = ram_result.stdout.strip().split()
                total_ram = int(ram_out[0])
                available_ram = int(ram_out[1])
            except Exception:
                total_ram = 0
                available_ram = 0

            try:
                total_cpu = int(cpu_cores_result.stdout.strip())
            except Exception:
                total_cpu = 0
                
            try:
                current_cpu_load = float(cpu_load_result.stdout.strip())
            except Exception:
                current_cpu_load = 0.0

            return {
                "total_ram": total_ram,
                "total_cpu": total_cpu,
                "current_cpu_load": current_cpu_load,
                "current_ram_available": available_ram,
                "status": "ALIVE"
            }
    except Exception as e:
        logger.error(f"Failed to connect to {worker.hostname} ({worker.ip_management}): {e}")
        return {
            "status": "DOWN"
        }

async def update_all_workers(db: AsyncSession):
    from sqlalchemy.future import select
    result = await db.execute(select(Worker))
    workers = result.scalars().all()
    
    for worker in workers:
        metrics = await fetch_worker_metrics(worker)
        
        if worker.total_ram == 0 and metrics.get("total_ram"):
            worker.total_ram = metrics["total_ram"]
        if worker.total_cpu == 0 and metrics.get("total_cpu"):
            worker.total_cpu = metrics["total_cpu"]
            
        if "current_cpu_load" in metrics:
            worker.current_cpu_load = metrics["current_cpu_load"]
        if "current_ram_available" in metrics:
            worker.current_ram_available = metrics["current_ram_available"]
            
        worker.status = metrics["status"]
        
    await db.commit()
