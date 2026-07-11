import os
from fastapi import APIRouter, Depends, HTTPException, Header
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.future import select

from database import get_db
import models, schemas

router = APIRouter()

async def get_current_user(x_user_role: str = Header(...), x_user_id: int = Header(...), db: AsyncSession = Depends(get_db)):
    result = await db.execute(select(models.User).where(models.User.id == x_user_id))
    user = result.scalar_one_or_none()
    if not user:
        raise HTTPException(status_code=403, detail="User not found")
    if user.role != x_user_role:
        raise HTTPException(status_code=403, detail="Role mismatch")
    return user

@router.get("/", response_model=list[schemas.FlavorResponse])
async def list_flavors(
    x_user_role: str = Header(...),
    x_user_id: int = Header(...),
    db: AsyncSession = Depends(get_db)
):
    user = await get_current_user(x_user_role, x_user_id, db)
    
    if user.role == "STUDENT":
        result = await db.execute(select(models.Flavor).where(models.Flavor.allowed_role == "STUDENT"))
    else:
        result = await db.execute(select(models.Flavor))
        
    flavors = result.scalars().all()
    return flavors

@router.post("/", response_model=schemas.FlavorResponse, status_code=201)
async def create_flavor(
    flavor_in: schemas.FlavorCreate,
    x_user_role: str = Header(...),
    x_user_id: int = Header(...),
    db: AsyncSession = Depends(get_db)
):
    user = await get_current_user(x_user_role, x_user_id, db)
    if user.role not in ["SYSTEM_ADMIN", "SLICE_ADMIN"]:
        raise HTTPException(status_code=403, detail="Only admins can create flavors")
        
    # Check if name exists
    existing = await db.execute(select(models.Flavor).where(models.Flavor.name == flavor_in.name))
    if existing.scalar_one_or_none():
        raise HTTPException(status_code=400, detail="Flavor name already exists")
        
    new_flavor = models.Flavor(
        name=flavor_in.name,
        ram=flavor_in.ram,
        vcpu=flavor_in.vcpu,
        disk=flavor_in.disk,
        allowed_role=flavor_in.allowed_role
    )
    db.add(new_flavor)
    await db.commit()
    await db.refresh(new_flavor)
    return new_flavor
