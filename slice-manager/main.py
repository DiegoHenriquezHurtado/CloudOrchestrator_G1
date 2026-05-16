import os
from fastapi import FastAPI
from routers import slices

app = FastAPI(title="Slice Manager")

app.include_router(slices.router, prefix="/slices", tags=["slices"])

if __name__ == "__main__":
    import uvicorn
    uvicorn.run(app, host="0.0.0.0", port=8082)
