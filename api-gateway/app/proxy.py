import httpx
from fastapi import Request, Response
from fastapi.responses import StreamingResponse
from starlette.background import BackgroundTask


async def forward_request(
    method: str,
    target_url: str,
    headers: dict,
    body: bytes = None
):
    async with httpx.AsyncClient(timeout=30.0) as client:
        response = await client.request(
            method=method,
            url=target_url,
            headers=headers,
            content=body
        )

        return Response(
            content=response.content,
            status_code=response.status_code,
            headers=dict(response.headers)
        )


async def stream_request(
    method: str,
    target_url: str,
    headers: dict,
    request: Request
):
    """
    Reenvía la petición en streaming (sin cargar el cuerpo completo en memoria).
    Se usa para uploads grandes (multipart/form-data), como la carga de
    imágenes de disco, donde el archivo puede pesar varios GB.
    """
    client = httpx.AsyncClient(timeout=httpx.Timeout(3600.0))
    req = client.build_request(
        method=method,
        url=target_url,
        headers=headers,
        content=request.stream()
    )
    response = await client.send(req, stream=True)

    async def close():
        await response.aclose()
        await client.aclose()

    return StreamingResponse(
        response.aiter_raw(),
        status_code=response.status_code,
        headers=dict(response.headers),
        background=BackgroundTask(close)
    )
