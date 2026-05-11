import os
from pathlib import Path
from fastapi import FastAPI, HTTPException
from pydantic import BaseModel

app = FastAPI(title="Image Manager Module", version="1.0")

# Variables de entorno
IMAGE_BASE_PATH = os.getenv("IMAGE_BASE_PATH", "/mnt/storage/base/")
INSTANCE_BASE_PATH = os.getenv("INSTANCE_BASE_PATH", "/mnt/storage/instances/")

class ProvisionRequest(BaseModel):
    vm_id: int
    base_image: str

@app.get("/images/")
def list_images():
    """Lista las imágenes base disponibles."""
    base_dir = Path(IMAGE_BASE_PATH)
    if not base_dir.exists() or not base_dir.is_dir():
        return {"images": []}
    
    images = []
    for file in base_dir.iterdir():
        if file.is_file() and file.name.endswith(".qcow2"):
            images.append(file.name)
    return {"images": images}

@app.get("/images/{name}/validate")
def validate_image(name: str):
    """Valida existencia de la imagen base y retorna la ruta absoluta o error 404."""
    if not name.endswith(".qcow2"):
        name = f"{name}.qcow2"
        
    image_path = Path(IMAGE_BASE_PATH) / name
    if not image_path.exists() or not image_path.is_file():
        raise HTTPException(status_code=404, detail="Imagen base no encontrada")
    
    return {"absolute_path": str(image_path)}

@app.post("/images/provision")
def provision_image(request: ProvisionRequest):
    """Recibe vm_id y base_image, retorna el instance_path y el comando qemu-img."""
    base_name = request.base_image
    if not base_name.endswith(".qcow2"):
        base_name = f"{base_name}.qcow2"
        
    base_path = Path(IMAGE_BASE_PATH) / base_name
    
    if not base_path.exists() or not base_path.is_file():
        raise HTTPException(status_code=404, detail="Imagen base no encontrada")
        
    instance_path = Path(INSTANCE_BASE_PATH) / f"{request.vm_id}.qcow2"
    
    cmd = f"qemu-img create -f qcow2 -b {base_path} {instance_path}"
    
    return {
        "instance_path": str(instance_path),
        "command": cmd
    }

if __name__ == "__main__":
    import uvicorn
    uvicorn.run(app, host="0.0.0.0", port=8083)
