from fastapi import APIRouter, Depends
from sqlalchemy.ext.asyncio import AsyncSession

from app.database import AsyncSessionLocal
from app.placement_service import PlacementService
from app.schemas import (
    PlacementStatusResponse,
    PlacementTriggerResponse
)

router = APIRouter()
service = PlacementService()


async def get_db():
    async with AsyncSessionLocal() as session:
        yield session


@router.get(
    "/placement/status",
    response_model=PlacementStatusResponse
)
async def status(db: AsyncSession = Depends(get_db)):
    return await service.status(db)


@router.post(
    "/placement/trigger",
    response_model=PlacementTriggerResponse
)
async def trigger(db: AsyncSession = Depends(get_db)):
    return await service.trigger(db)
