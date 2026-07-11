from fastapi import FastAPI, Request, HTTPException
from fastapi.middleware.cors import CORSMiddleware

from app.auth import decode_token
from app.proxy import forward_request
from app.routes import ROUTE_MAP, ROLE_RULES
from app.config import MAX_BODY_SIZE

app = FastAPI(title="API Gateway")

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],  # desarrollo
    allow_methods=["GET", "POST", "PUT", "DELETE", "OPTIONS"],
    allow_headers=["Content-Type", "Authorization"]
)

@app.get("/health")
async def health():
    return {
        "status": "ok",
        "services": {
            "auth": "up",
            "slice-manager": "up",
            "monitoring": "up"
        }
    }

@app.api_route("/api/v1/{service}/{path:path}",
               methods=["GET", "POST", "PUT", "DELETE", "OPTIONS"])
async def gateway(service: str, path: str, request: Request):

    if service not in ROUTE_MAP:
        raise HTTPException(status_code=404, detail="Servicio no encontrado")

    body = await request.body()

    if len(body) > MAX_BODY_SIZE:
        raise HTTPException(
            status_code=413,
            detail="Payload excede 2MB"
        )

    if service == "auth":
        return await forward_request(
            request.method,
            f"{ROUTE_MAP[service]}/{path}",
            dict(request.headers),
            body
        )

    auth_header = request.headers.get("Authorization")

    if not auth_header:
        raise HTTPException(status_code=401, detail="Token requerido")

    token = auth_header.replace("Bearer ", "")
    payload = decode_token(token)

    user_role = payload["role"]
    user_id = payload["sub"]

    if user_role not in ROLE_RULES[service]:
        raise HTTPException(status_code=403, detail="Acceso denegado")

    headers = dict(request.headers)
    headers["X-User-Id"] = str(user_id)
    headers["X-User-Role"] = user_role

    target_url = f"{ROUTE_MAP[service]}/{path}"

    return await forward_request(
        request.method,
        target_url,
        headers,
        body
    )
