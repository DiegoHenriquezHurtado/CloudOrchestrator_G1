"""
Dispatcher — Módulo orquestador de tareas (Puerto 8087)

Loop principal que consume tareas PLACEMENT_READY de la BD
y las despacha al Driver para ejecución en los Workers.
"""

import os
import asyncio
import logging
from contextlib import asynccontextmanager

from fastapi import FastAPI, Depends
from sqlalchemy.ext.asyncio import AsyncSession

from database import get_db, AsyncSessionLocal
from dispatcher_service import DispatcherService

logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(name)s] %(levelname)s: %(message)s")
logger = logging.getLogger("dispatcher")

POLL_INTERVAL = int(os.getenv("POLL_INTERVAL_SECONDS", "5"))

service = DispatcherService()
polling_task = None


# ------------------------------------------------------------------
# Background polling loop
# ------------------------------------------------------------------
async def polling_loop():
    """Loop infinito que busca tareas PLACEMENT_READY cada N segundos."""
    logger.info(f"Polling loop started (interval={POLL_INTERVAL}s)")
    while True:
        try:
            async with AsyncSessionLocal() as db:
                result = await service.process_tasks(db)
                dispatched = result.get("dispatched", [])
                errors = result.get("errors", [])
                if dispatched or errors:
                    logger.info(f"Poll cycle: {len(dispatched)} dispatched, {len(errors)} errors")
        except Exception as e:
            logger.error(f"Polling cycle error: {e}")
        await asyncio.sleep(POLL_INTERVAL)


# ------------------------------------------------------------------
# App lifecycle
# ------------------------------------------------------------------
@asynccontextmanager
async def lifespan(app: FastAPI):
    global polling_task
    polling_task = asyncio.create_task(polling_loop())
    logger.info("Dispatcher started")
    yield
    polling_task.cancel()
    logger.info("Dispatcher stopped")


app = FastAPI(title="Dispatcher", lifespan=lifespan)


# ------------------------------------------------------------------
# Endpoints
# ------------------------------------------------------------------
@app.get("/dispatcher/status")
async def status(db: AsyncSession = Depends(get_db)):
    """Estado actual del Dispatcher y métricas de tareas."""
    return await service.get_status(db)


@app.post("/dispatcher/trigger")
async def trigger(db: AsyncSession = Depends(get_db)):
    """Forzar una iteración del loop de despacho (para debug/testing)."""
    result = await service.process_tasks(db)
    return result


@app.get("/health")
async def health():
    return {"status": "ok", "service": "dispatcher", "polling_active": polling_task is not None and not polling_task.done()}


if __name__ == "__main__":
    import uvicorn
    uvicorn.run(app, host="0.0.0.0", port=8087)
