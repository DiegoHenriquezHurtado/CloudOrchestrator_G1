import os
import asyncio
import posixpath
from fastapi import FastAPI, HTTPException, UploadFile, File, Header
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

@app.post("/images/upload")
async def upload_image(
    file: UploadFile = File(...),
    x_user_role: str = Header(...)
):
    if x_user_role != "SYSTEM_ADMIN":
        raise HTTPException(status_code=403, detail="Solo SYSTEM_ADMIN puede subir imágenes")

    filename = file.filename
    if not (filename.endswith(".qcow2") or filename.endswith(".img")):
        raise HTTPException(status_code=400, detail="Solo se permiten archivos .qcow2 o .img")

    needs_conversion = filename.endswith(".img")
    final_name = filename.removesuffix(".img") + ".qcow2" if needs_conversion else filename

    os.makedirs(IMAGE_BASE_PATH, exist_ok=True)
    final_dest = os.path.join(IMAGE_BASE_PATH, final_name)

    if os.path.exists(final_dest):
        raise HTTPException(status_code=409, detail=f"La imagen {final_name} ya existe")

    # Ruta temporal para el .img antes de convertir
    upload_dest = os.path.join(IMAGE_BASE_PATH, filename) if needs_conversion else final_dest

    try:
        with open(upload_dest, "wb") as f:
            while chunk := await file.read(1024 * 1024):
                f.write(chunk)

        if needs_conversion:
            proc = await asyncio.create_subprocess_exec(
                "qemu-img", "convert", "-O", "qcow2", upload_dest, final_dest,
                stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.PIPE,
            )
            _, stderr = await proc.communicate()
            os.remove(upload_dest)
            if proc.returncode != 0:
                raise HTTPException(status_code=500, detail=f"Conversión fallida: {stderr.decode().strip()}")

    except HTTPException:
        raise
    except Exception as e:
        for path in (upload_dest, final_dest):
            if os.path.exists(path):
                os.remove(path)
        raise HTTPException(status_code=500, detail=f"Error procesando imagen: {str(e)}")

    size_mb = os.path.getsize(final_dest) // (1024 * 1024)
    return {
        "name": final_name,
        "original": filename if needs_conversion else None,
        "converted": needs_conversion,
        "path": posixpath.join(IMAGE_BASE_PATH, final_name),
        "size_mb": size_mb,
        "status": "uploaded"
    }


@app.delete("/images/{name}")
def delete_image(name: str, x_user_role: str = Header(...)):
    if x_user_role != "SYSTEM_ADMIN":
        raise HTTPException(status_code=403, detail="Solo SYSTEM_ADMIN puede eliminar imágenes")
    if not name.endswith(".qcow2"):
        raise HTTPException(status_code=400, detail="Solo se pueden eliminar archivos .qcow2")
    local_filepath = os.path.join(IMAGE_BASE_PATH, name)
    if not os.path.exists(local_filepath) or not os.path.isfile(local_filepath):
        raise HTTPException(status_code=404, detail="Imagen no encontrada")
    os.remove(local_filepath)
    return {"name": name, "status": "deleted"}


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
