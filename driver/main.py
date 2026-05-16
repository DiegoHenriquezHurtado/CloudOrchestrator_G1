"""
Driver — Capa de ejecución en Workers (Puerto 8088)

Recibe instrucciones del Dispatcher y ejecuta comandos SSH
en los Workers (QEMU, OVS, iptables).

Es un servicio stateless: no accede a la BD directamente.
El Dispatcher gestiona toda la persistencia.
"""

import logging
from fastapi import FastAPI
from schemas import ExecuteRequest, ExecuteSuccessResponse, ExecuteFailureResponse
from driver_service import DriverService
from ssh_client import SSH_ENABLED

logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(name)s] %(levelname)s: %(message)s")
logger = logging.getLogger("driver")

app = FastAPI(title="Driver")
service = DriverService()


@app.post("/driver/execute")
async def execute(request: ExecuteRequest):
    """
    Ejecuta una tarea de despliegue/cleanup en un Worker.
    
    Recibe el payload completo del Dispatcher y ejecuta los
    comandos SSH correspondientes según el task_type.
    """
    logger.info(f"Execute task_id={request.task_id} type={request.task_type} worker={request.worker_ip}")

    try:
        result = await service.execute(request)
        
        if isinstance(result, ExecuteFailureResponse):
            logger.warning(f"Task {request.task_id} FAILED: {result.error_msg[:100]}")
            return result.model_dump()
        
        logger.info(f"Task {request.task_id} READY (pid={result.process_id}, vnc={result.vnc_port})")
        return result.model_dump()

    except Exception as e:
        logger.error(f"Task {request.task_id} unexpected error: {e}")
        return ExecuteFailureResponse(
            task_id=request.task_id,
            status="FAILED",
            error_msg=f"Unexpected error: {str(e)[:300]}",
        ).model_dump()


@app.get("/health")
async def health():
    return {
        "status": "ok",
        "service": "driver",
        "ssh_enabled": SSH_ENABLED,
    }


if __name__ == "__main__":
    import uvicorn
    uvicorn.run(app, host="0.0.0.0", port=8088)
