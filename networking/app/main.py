from fastapi import FastAPI
from app.api import router

app = FastAPI(title="Networking Module", description="Orchestrator Network Management")

app.include_router(router)
