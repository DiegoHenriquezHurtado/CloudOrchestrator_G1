import asyncio
from fastapi import FastAPI
from contextlib import asynccontextmanager
from database import AsyncSessionLocal
from service import update_all_workers_metrics
from router import router
import os

POLL_INTERVAL = int(os.getenv("POLL_INTERVAL", "60"))

async def poll_workers():
    while True:
        try:
            async with AsyncSessionLocal() as session:
                await update_all_workers_metrics(session)
        except Exception as e:
            print(f"Error polling workers: {e}")
        
        await asyncio.sleep(POLL_INTERVAL)

@asynccontextmanager
async def lifespan(app: FastAPI):
    # Startup: Start polling task
    task = asyncio.create_task(poll_workers())
    yield
    # Shutdown: Cancel task
    task.cancel()
    try:
        await task
    except asyncio.CancelledError:
        pass

app = FastAPI(title="Monitoring Service", lifespan=lifespan)

app.include_router(router)
