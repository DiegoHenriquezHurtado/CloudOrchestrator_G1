import os
import posixpath
from fastapi import FastAPI, HTTPException
from pydantic import BaseModel

app = FastAPI(
    title="Image Manager",
    description="Gestión de imágenes base y thin provisioning para el Orquestador Cloud"
)

# Rutas configurables
IMAGE_BASE_PATH = os.getenv("IMAGE_BASE_PATH", "/mnt/storage/base/")
IMAGE_INSTANCES_PATH = os.getenv("IMAGE_INSTANCES_PATH", "/mnt/storage/instances/")

class ProvisionRequest(BaseModel):
    vm_id: int
    base_image: str

@app.get("/images/")
def list_images():
    images = []
    # Se usa os.path para validar el sistema de archivos local o del contenedor
    if os.path.exists(IMAGE_BASE_PATH):
        for filename in os.listdir(IMAGE_BASE_PATH):
            if filename.endswith(".qcow2"):
                local_filepath = os.path.join(IMAGE_BASE_PATH, filename)
                # Para la respuesta y comandos (que irán al driver/QEMU) usamos posixpath
                posix_filepath = posixpath.join(IMAGE_BASE_PATH, filename)
                size_mb = os.path.getsize(local_filepath) // (1024 * 1024)
                images.append({
                    "name": filename,
                    "size_mb": size_mb,
                    "path": posix_filepath
                })
    return {"images": images}

@app.get("/images/{name}/validate")
def validate_image(name: str):
    local_filepath = os.path.join(IMAGE_BASE_PATH, name)
    if os.path.exists(local_filepath) and os.path.isfile(local_filepath) and name.endswith(".qcow2"):
        posix_filepath = posixpath.join(IMAGE_BASE_PATH, name)
        return {
            "exists": True,
            "name": name,
            "path": posix_filepath
        }
    raise HTTPException(status_code=404, detail="Imagen base no encontrada")

@app.post("/images/provision")
def provision_image(request: ProvisionRequest):
    local_base_path = os.path.join(IMAGE_BASE_PATH, request.base_image)
    if not os.path.exists(local_base_path) or not os.path.isfile(local_base_path):
        raise HTTPException(status_code=404, detail="Imagen base no encontrada")
    
    posix_base_path = posixpath.join(IMAGE_BASE_PATH, request.base_image)
    posix_instance_path = posixpath.join(IMAGE_INSTANCES_PATH, f"{request.vm_id}.qcow2")
    
    command = f"qemu-img create -f qcow2 -b {posix_base_path} {posix_instance_path}"
    
    return {
        "vm_id": request.vm_id,
        "base_path": posix_base_path,
        "instance_path": posix_instance_path,
        "command": command
    }
