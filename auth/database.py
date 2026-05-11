import os
from sqlalchemy.ext.asyncio import create_async_engine, async_sessionmaker, AsyncSession
from sqlalchemy.orm import declarative_base

# The application connects using DATABASE_URL. In local docker-compose it will be provided.
DATABASE_URL = os.getenv("DATABASE_URL", "postgresql+asyncpg://orchestrator:orchestrator@localhost:5432/orchestrator_db")

engine = create_async_engine(DATABASE_URL, echo=False)
SessionLocal = async_sessionmaker(autocommit=False, autoflush=False, bind=engine, class_=AsyncSession)
Base = declarative_base()

async def get_db():
    async with SessionLocal() as session:
        yield session
