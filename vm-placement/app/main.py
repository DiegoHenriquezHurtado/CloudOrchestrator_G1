from fastapi import FastAPI
from app.api import router

app = FastAPI(title="VM Placement")

app.include_router(router)
