import os
from fastapi import FastAPI
from routers import slices, flavors

app = FastAPI(title="Slice Manager")

app.include_router(slices.router, prefix="/slices", tags=["slices"])
app.include_router(flavors.router, prefix="/flavors", tags=["flavors"])

if __name__ == "__main__":
    import uvicorn
    uvicorn.run(app, host="0.0.0.0", port=8082)
