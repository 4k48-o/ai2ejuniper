"""Tests for webhook management API."""

import uuid
from datetime import datetime, timezone
from unittest.mock import AsyncMock, MagicMock

import pytest
from httpx import ASGITransport, AsyncClient

from juniper_ai.app.api.middleware.auth import AuthContext
from juniper_ai.app.config import settings
from juniper_ai.app.main import app


@pytest.mark.asyncio
async def test_register_webhook_returns_201():
    mock_db = AsyncMock()
    mock_db.add = MagicMock()
    mock_db.flush = AsyncMock()
    mock_db.commit = AsyncMock()
    mock_db.rollback = AsyncMock()

    auth = AuthContext(user_id="ext-1", auth_type="api_key", external_user_id="ext-1")

    from juniper_ai.app.db.session import get_db
    from juniper_ai.app.api.middleware.auth import get_auth_context

    app.dependency_overrides[get_db] = lambda: mock_db
    app.dependency_overrides[get_auth_context] = lambda: auth

    try:

        def _flush_side_effect():
            for call in mock_db.add.call_args_list:
                obj = call[0][0]
                if getattr(obj, "id", None) is None:
                    obj.id = uuid.uuid4()
                if getattr(obj, "created_at", None) is None:
                    obj.created_at = datetime.now(timezone.utc)

        mock_db.flush.side_effect = _flush_side_effect

        async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
            response = await client.post(
                "/api/v1/webhooks",
                headers={"X-API-Key": settings.api_keys_list[0]},
                json={
                    "url": "https://api.example.com/hook",
                    "events": ["booking.confirmed"],
                    "secret": "a" * 16,
                },
            )
        assert response.status_code == 201
        data = response.json()
        assert "id" in data
        assert data["url"] == "https://api.example.com/hook"
    finally:
        app.dependency_overrides.clear()


@pytest.mark.asyncio
async def test_register_webhook_invalid_event_returns_400():
    mock_db = AsyncMock()
    mock_db.add = MagicMock()
    mock_db.flush = AsyncMock()

    auth = AuthContext(user_id="ext-1", auth_type="api_key", external_user_id="ext-1")

    from juniper_ai.app.db.session import get_db
    from juniper_ai.app.api.middleware.auth import get_auth_context

    app.dependency_overrides[get_db] = lambda: mock_db
    app.dependency_overrides[get_auth_context] = lambda: auth

    try:
        async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
            response = await client.post(
                "/api/v1/webhooks",
                headers={"X-API-Key": settings.api_keys_list[0]},
                json={
                    "url": "https://api.example.com/hook",
                    "events": ["booking.unknown_event"],
                    "secret": "a" * 16,
                },
            )
        assert response.status_code == 400
        assert "Invalid events" in response.json()["detail"]
        mock_db.add.assert_not_called()
    finally:
        app.dependency_overrides.clear()


@pytest.mark.asyncio
async def test_register_webhook_short_secret_returns_400():
    mock_db = AsyncMock()
    mock_db.add = MagicMock()
    mock_db.flush = AsyncMock()

    auth = AuthContext(user_id="ext-1", auth_type="api_key", external_user_id="ext-1")

    from juniper_ai.app.db.session import get_db
    from juniper_ai.app.api.middleware.auth import get_auth_context

    app.dependency_overrides[get_db] = lambda: mock_db
    app.dependency_overrides[get_auth_context] = lambda: auth

    try:
        async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
            response = await client.post(
                "/api/v1/webhooks",
                headers={"X-API-Key": settings.api_keys_list[0]},
                json={
                    "url": "https://api.example.com/hook",
                    "events": ["booking.confirmed"],
                    "secret": "a" * 15,
                },
            )
        assert response.status_code == 400
        assert "16 characters" in response.json()["detail"]
        mock_db.add.assert_not_called()
    finally:
        app.dependency_overrides.clear()
