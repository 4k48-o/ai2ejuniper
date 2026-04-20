"""Tests for the health endpoint."""

import pytest
from httpx import ASGITransport, AsyncClient

from juniper_ai.app.main import app


@pytest.mark.asyncio
async def test_health_check():
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        response = await client.get("/api/v1/health")
    assert response.status_code == 200
    data = response.json()
    assert data["status"] == "healthy"
    assert data["version"] == "0.1.0"


@pytest.mark.asyncio
async def test_health_response_includes_x_request_id():
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        response = await client.get("/api/v1/health")
    assert response.status_code == 200
    rid = response.headers.get("x-request-id")
    assert rid
    assert len(rid) >= 8


@pytest.mark.asyncio
async def test_x_request_id_echo_from_client_header():
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        response = await client.get(
            "/api/v1/health",
            headers={"X-Request-ID": "upstream-trace-abc"},
        )
    assert response.status_code == 200
    assert response.headers.get("x-request-id") == "upstream-trace-abc"
