import httpx
from fastapi import Response


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
