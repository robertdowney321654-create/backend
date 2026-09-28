"""Health endpoint tests."""

import asyncio

import httpx

from app.main import app



async def get_response(path: str) -> httpx.Response:
    """Request an endpoint through the ASGI app without opening a socket."""
    transport = httpx.ASGITransport(app=app)
    async with httpx.AsyncClient(transport=transport, base_url="http://testserver") as client:
        return await client.get(path)


def test_health() -> None:
    response = asyncio.run(get_response("/health"))
    assert response.status_code == 200
    assert response.json() == {"status": "ok"}


def test_versioned_health() -> None:
    response = asyncio.run(get_response("/api/v1/health"))
    assert response.status_code == 200
    assert response.json() == {"status": "ok"}
