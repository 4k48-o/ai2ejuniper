"""Tests for authentication middleware (JWT + API key)."""

import time

import pytest
from fastapi import HTTPException
from jose import jwt
from unittest.mock import AsyncMock, MagicMock, patch

from juniper_ai.app.api.middleware.auth import AuthContext, get_auth_context
from juniper_ai.app.config import settings


def _make_jwt(payload: dict, secret: str | None = None, algorithm: str = "HS256") -> str:
    return jwt.encode(payload, secret or settings.jwt_secret_key, algorithm=algorithm)


def _mock_request(headers: dict | None = None):
    """Build a minimal mock Request."""
    req = MagicMock()
    req.headers = headers or {}
    return req


def _mock_credentials(token: str):
    cred = MagicMock()
    cred.credentials = token
    return cred


# --- JWT tests ---


@pytest.mark.asyncio
async def test_valid_jwt_returns_auth_context():
    token = _make_jwt({"sub": "user-123", "exp": int(time.time()) + 3600})
    ctx = await get_auth_context(
        request=_mock_request(),
        credentials=_mock_credentials(token),
        api_key=None,
    )
    assert ctx.user_id == "user-123"
    assert ctx.auth_type == "jwt"
    assert ctx.external_user_id is None


@pytest.mark.asyncio
async def test_expired_jwt_returns_401():
    token = _make_jwt({"sub": "user-123", "exp": int(time.time()) - 3600})
    with pytest.raises(HTTPException) as exc_info:
        await get_auth_context(
            request=_mock_request(),
            credentials=_mock_credentials(token),
            api_key=None,
        )
    assert exc_info.value.status_code == 401


@pytest.mark.asyncio
async def test_invalid_jwt_returns_401():
    with pytest.raises(HTTPException) as exc_info:
        await get_auth_context(
            request=_mock_request(),
            credentials=_mock_credentials("not-a-valid-token"),
            api_key=None,
        )
    assert exc_info.value.status_code == 401


@pytest.mark.asyncio
async def test_jwt_missing_sub_returns_401():
    token = _make_jwt({"exp": int(time.time()) + 3600})
    with pytest.raises(HTTPException) as exc_info:
        await get_auth_context(
            request=_mock_request(),
            credentials=_mock_credentials(token),
            api_key=None,
        )
    assert exc_info.value.status_code == 401
    assert "sub" in exc_info.value.detail.lower()


@pytest.mark.asyncio
async def test_empty_bearer_token_returns_401():
    with pytest.raises(HTTPException) as exc_info:
        await get_auth_context(
            request=_mock_request(),
            credentials=_mock_credentials(""),
            api_key=None,
        )
    assert exc_info.value.status_code == 401
    assert "empty" in exc_info.value.detail.lower()


# --- API key tests ---


@pytest.mark.asyncio
async def test_valid_api_key_returns_auth_context():
    api_key = settings.api_keys_list[0]
    ctx = await get_auth_context(
        request=_mock_request(),
        credentials=None,
        api_key=api_key,
    )
    assert ctx.auth_type == "api_key"
    assert ctx.user_id == f"apikey:{api_key[:8]}"


@pytest.mark.asyncio
async def test_invalid_api_key_returns_401():
    with pytest.raises(HTTPException) as exc_info:
        await get_auth_context(
            request=_mock_request(),
            credentials=None,
            api_key="bad-key-does-not-exist",
        )
    assert exc_info.value.status_code == 401


@pytest.mark.asyncio
async def test_api_key_with_external_user_id_header():
    api_key = settings.api_keys_list[0]
    ctx = await get_auth_context(
        request=_mock_request(headers={"X-External-User-Id": "ext-user-99"}),
        credentials=None,
        api_key=api_key,
    )
    assert ctx.auth_type == "api_key"
    assert ctx.user_id == "ext-user-99"
    assert ctx.external_user_id == "ext-user-99"


# --- No auth ---


@pytest.mark.asyncio
async def test_no_auth_header_returns_401():
    with pytest.raises(HTTPException) as exc_info:
        await get_auth_context(
            request=_mock_request(),
            credentials=None,
            api_key=None,
        )
    assert exc_info.value.status_code == 401
    assert "Authentication required" in exc_info.value.detail
