"""
OpenStack Driver — Microservicio de Provisión en la Nube (Puerto 8089)

Recibe instrucciones de despliegue para infraestructuras Multi-IaaS,
e interactúa con el plano de control del clúster OpenStack.
"""

import logging
from fastapi import FastAPI, status, HTTPException, UploadFile, File, Form
from fastapi.responses import JSONResponse

from app.schemas import (
    CreateSliceRequest,
    CreateSliceResponse,
    DeleteSliceRequest,
    DeleteSliceResponse
)
from app.orchestrator import OpenStackOrchestrator
from app.config import settings

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(name)s] %(levelname)s: %(message)s"
)
logger = logging.getLogger("openstack-driver")

app = FastAPI(
    title="PUCP Private Cloud - OpenStack Driver",
    description="Driver de aprovisionamiento de Slices sobre OpenStack Cluster",
    version="2.0.0"
)

orchestrator = OpenStackOrchestrator(settings=settings)


@app.post(
    "/v1/vms/create",
    response_model=CreateSliceResponse,
    status_code=status.HTTP_201_CREATED,
    summary="Crea un Slice completo en OpenStack de forma aislada (Multi-tenant)"
)
async def create_slice(request: CreateSliceRequest):
    """
    Endpoint para desplegar un Slice en OpenStack.
    
    Flujo atómico:
    1. Autentica como admin y crea el Proyecto (Tenant) y Usuario en Keystone.
    2. Asigna roles y obtiene un scoped token para el proyecto.
    3. Resuelve el UUID de la red Provider (compartida/inmutable).
    4. Crea redes y subredes internas virtuales.
    5. Crea puertos en las redes correspondientes (asignación dinámica en Provider).
    6. Lanza las instancias conectadas a dichos puertos.
    7. Monitorea que las VMs estén en estado ACTIVE.
    
    En caso de cualquier fallo en la API de OpenStack, se ejecuta
    de inmediato la rutina de Rollback para evitar recursos huérfanos.
    """
    logger.info(f"Iniciando despliegue de Slice: {request.slice_id}")
    
    try:
        result = await orchestrator.provision_slice(request)
        logger.info(f"Slice {request.slice_id} desplegado exitosamente con ID Proyecto: {result.project_id}")
        return result

    except Exception as e:
        logger.error(f"Error crítico en el despliegue del slice {request.slice_id}: {str(e)}")
        
        # Ejecución del Rollback ante fallos
        rollback_msg = await orchestrator.rollback_slice(request.slice_id)
        logger.warning(f"Resultado del rollback para {request.slice_id}: {rollback_msg}")
        
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail={
                "message": "Fallo en la creación de recursos de OpenStack. Rollback ejecutado.",
                "error": str(e),
                "rollback_status": rollback_msg
            }
        )


@app.post(
    "/v1/vms/delete",
    response_model=DeleteSliceResponse,
    status_code=status.HTTP_200_OK,
    summary="Elimina un Slice y limpia en cascada todos sus recursos"
)
async def delete_slice(request: DeleteSliceRequest):
    """
    Endpoint para limpiar y destruir un Slice en OpenStack.
    
    Limpia en cascada de forma segura:
    1. Termina todas las instancias asociadas al proyecto.
    2. Elimina los puertos de red asignados (incluyendo puertos en la red Provider).
    3. Elimina subredes y redes privadas creadas para el slice.
    4. Elimina el usuario y finalmente el proyecto de Keystone.
    
    REGLA CRÍTICA: La red Provider externa compartida no se elimina bajo ninguna circunstancia.
    """
    logger.info(f"Iniciando eliminación del Slice: {request.slice_id}")
    
    try:
        cleanup_summary = await orchestrator.deprovision_slice(request.slice_id)
        logger.info(f"Slice {request.slice_id} eliminado y purgado correctamente.")
        return DeleteSliceResponse(
            slice_id=request.slice_id,
            status="DELETED",
            message=f"Limpieza completada con éxito. Detalle: {cleanup_summary}"
        )

    except Exception as e:
        logger.error(f"Error al eliminar el slice {request.slice_id}: {str(e)}")
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail={
                "message": "Error durante la limpieza de recursos en OpenStack.",
                "error": str(e)
            }
        )


@app.get("/health", summary="Chequeo de salud del Driver")
async def health():
    """Retorna el estado de disponibilidad del driver y conexión al API de OpenStack"""
    openstack_connected = await orchestrator.check_api_connectivity()
    return {
        "status": "ok" if openstack_connected else "degraded",
        "service": "openstack-driver",
        "openstack_api_reachable": openstack_connected
    }

@app.get("/v1/flavors", summary="Listar flavors disponibles en Nova")
async def list_flavors():
    """Retorna el catálogo de flavors de Nova (id, name, ram, vcpus, disk) para poblar selects en el frontend"""
    try:
        flavors = await orchestrator.list_flavors()
        return {"flavors": flavors}
    except Exception as e:
        logger.error(f"Error listando flavors: {str(e)}")
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail={"message": "Error al listar flavors en OpenStack", "error": str(e)}
        )


@app.get("/v1/images", summary="Listar imágenes disponibles en Glance")
async def list_images():
    """Retorna el catálogo de imágenes de Glance (id, name, status) para poblar selects en el frontend"""
    try:
        images = await orchestrator.list_images()
        return {"images": images}
    except Exception as e:
        logger.error(f"Error listando imágenes: {str(e)}")
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail={"message": "Error al listar imágenes en OpenStack", "error": str(e)}
        )


@app.post(
    "/v1/images",
    status_code=status.HTTP_201_CREATED,
    summary="Cargar e importar una imagen de disco en Glance (independiente de la plataforma de origen)"
)
async def upload_image(
    name: str = Form(...),
    file: UploadFile = File(...),
    disk_format: str = Form("qcow2"),
    container_format: str = Form("bare"),
    visibility: str = Form("public"),
):
    """
    Recibe un archivo de imagen (.img/.qcow2) vía multipart/form-data y lo
    registra públicamente en Glance con el formato de disco indicado (QCOW2 por defecto).
    """
    if not file.filename or not file.filename.lower().endswith((".img", ".qcow2")):
        raise HTTPException(status_code=400, detail="Solo se aceptan archivos con extensión .img o .qcow2")

    try:
        result = await orchestrator.upload_image(name, disk_format, container_format, visibility, file)
        logger.info(f"Imagen '{name}' registrada y cargada en Glance con ID {result['id']}")
        return result
    except Exception as e:
        logger.error(f"Error subiendo la imagen '{name}': {str(e)}")
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail={"message": "Error al subir la imagen a OpenStack Glance", "error": str(e)}
        )
    finally:
        await file.close()


@app.delete(
    "/v1/images/{image_id}",
    summary="Eliminar una imagen de Glance (borrado seguro tras validación)"
)
async def delete_image(image_id: str):
    """Elimina la imagen indicada del servicio Glance."""
    try:
        await orchestrator.delete_image(image_id)
        logger.info(f"Imagen {image_id} eliminada de Glance")
        return {"id": image_id, "status": "DELETED"}
    except Exception as e:
        logger.error(f"Error eliminando la imagen {image_id}: {str(e)}")
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail={"message": "Error al eliminar la imagen en OpenStack Glance", "error": str(e)}
        )


@app.get("/v1/flavors/{flavor_id}", summary="Obtener detalles de un flavor")
async def get_flavor(flavor_id: str):
    """Retorna los detalles de un flavor desde Nova (ram, vcpus, disk)"""
    try:
        flavor = await orchestrator.get_flavor(flavor_id)
        if not flavor:
            raise HTTPException(status_code=404, detail="Flavor no encontrado")
        return flavor
    except Exception as e:
        logger.error(f"Error obteniendo flavor {flavor_id}: {str(e)}")
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail={"message": "Error al consultar flavor en OpenStack", "error": str(e)}
        )
import asyncio

@app.get("/v1/vms/{server_id}/vnc", summary="Obtener consola VNC fresca")
async def get_vnc_console(server_id: str):
    """Genera y retorna una URL de consola VNC fresca desde Nova"""
    try:
        loop = asyncio.get_running_loop()
        admin_token = await loop.run_in_executor(
            None,
            orchestrator.client.get_admin_token,
            orchestrator.settings.DOMAIN_ID,
            orchestrator.settings.ADMIN_PROJECT_ID,
            orchestrator.settings.ADMIN_USER_ID,
            orchestrator.settings.ADMIN_USER_PASSWORD
        )
        vnc_url = await loop.run_in_executor(
            None,
            orchestrator.client.get_vnc_console,
            admin_token,
            server_id
        )
        return {"vnc_url": vnc_url}
    except Exception as e:
        logger.error(f"Error obteniendo consola VNC para {server_id}: {str(e)}")
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail={"message": "Error al obtener consola VNC", "error": str(e)}
        )



if __name__ == "__main__":
    import uvicorn
    uvicorn.run("main:app", host="0.0.0.0", port=8089, reload=True)
