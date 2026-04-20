"""Tests for preferences ownership enforcement."""

import uuid
from unittest.mock import AsyncMock, MagicMock

import pytest
from httpx import ASGITransport, AsyncClient

from juniper_ai.app.api.middleware.auth import AuthContext
from juniper_ai.app.main import app


def _fake_user(external_id: str = "user-abc"):
    user = MagicMock()
    user.id = uuid.uuid4()
    user.external_id = external_id
    user.preferences = {"star_rating": "4 stars"}
    return user


def _setup_overrides(auth: AuthContext, user=None):
    """Set dependency overrides and return the mock db."""
    mock_db = AsyncMock()
    result_mock = MagicMock()
    result_mock.scalar_one_or_none.return_value = user
    mock_db.execute = AsyncMock(return_value=result_mock)
    mock_db.flush = AsyncMock()
    mock_db.commit = AsyncMock()
    mock_db.rollback = AsyncMock()

    from juniper_ai.app.db.session import get_db
    from juniper_ai.app.api.middleware.auth import get_auth_context

    app.dependency_overrides[get_db] = lambda: mock_db
    app.dependency_overrides[get_auth_context] = lambda: auth
    return mock_db


# --- GET preferences ---


@pytest.mark.asyncio
async def test_get_preferences_own_user_returns_200():
    user = _fake_user("user-abc")
    auth = AuthContext(user_id="user-abc", auth_type="jwt")
    _setup_overrides(auth, user)

    try:
        async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
            response = await client.get("/api/v1/users/user-abc/preferences")
        assert response.status_code == 200
        data = response.json()
        assert data["preferences"]["star_rating"] == "4 stars"
    finally:
        app.dependency_overrides.clear()


@pytest.mark.asyncio
async def test_get_preferences_different_user_returns_403():
    auth = AuthContext(user_id="user-abc", auth_type="jwt")
    _setup_overrides(auth)

    try:
        async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
            response = await client.get("/api/v1/users/other-user/preferences")
        assert response.status_code == 403
    finally:
        app.dependency_overrides.clear()


@pytest.mark.parametrize("stored_prefs", [None, {}])
@pytest.mark.asyncio
async def test_get_preferences_empty_when_none_or_empty_dict(stored_prefs):
    """PREF-04: GET returns 200 with preferences == {} when DB has no keys."""
    user = MagicMock()
    user.id = uuid.uuid4()
    user.external_id = "user-no-prefs"
    user.preferences = stored_prefs

    auth = AuthContext(user_id="user-no-prefs", auth_type="jwt")
    _setup_overrides(auth, user)

    try:
        async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
            response = await client.get("/api/v1/users/user-no-prefs/preferences")
        assert response.status_code == 200
        data = response.json()
        assert data["preferences"] == {}
        assert data["user_id"] == str(user.id)
    finally:
        app.dependency_overrides.clear()


# --- PUT preferences ---


@pytest.mark.asyncio
async def test_put_preferences_own_user_returns_200():
    user = _fake_user("user-abc")
    auth = AuthContext(user_id="user-abc", auth_type="jwt")
    _setup_overrides(auth, user)

    try:
        async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
            response = await client.put(
                "/api/v1/users/user-abc/preferences",
                json={"star_rating": "5 stars", "board_type": "All Inclusive"},
            )
        assert response.status_code == 200
        data = response.json()
        assert data["preferences"]["star_rating"] == "5 stars"
    finally:
        app.dependency_overrides.clear()


@pytest.mark.asyncio
async def test_put_preferences_different_user_returns_403():
    auth = AuthContext(user_id="user-abc", auth_type="jwt")
    _setup_overrides(auth)

    try:
        async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
            response = await client.put(
                "/api/v1/users/other-user/preferences",
                json={"star_rating": "3 stars"},
            )
        assert response.status_code == 403
    finally:
        app.dependency_overrides.clear()


@pytest.mark.asyncio
async def test_put_preferences_merge_preserves_unsent_fields():
    """PREF-06: partial PUT merges; keys not in body stay from existing preferences."""
    user = MagicMock()
    user.id = uuid.uuid4()
    user.external_id = "user-abc"
    user.preferences = {
        "star_rating": "4 stars",
        "board_type": "Bed & Breakfast",
        "smoking": "non-smoking",
    }

    auth = AuthContext(user_id="user-abc", auth_type="jwt")
    _setup_overrides(auth, user)

    try:
        async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
            response = await client.put(
                "/api/v1/users/user-abc/preferences",
                json={"star_rating": "5 stars"},
            )
        assert response.status_code == 200
        data = response.json()
        assert data["preferences"]["star_rating"] == "5 stars"
        assert data["preferences"]["board_type"] == "Bed & Breakfast"
        assert data["preferences"]["smoking"] == "non-smoking"
    finally:
        app.dependency_overrides.clear()


@pytest.mark.asyncio
async def test_put_preferences_all_optional_fields():
    """PREF-08: all documented preference keys can be set in one request."""
    user = MagicMock()
    user.id = uuid.uuid4()
    user.external_id = "user-abc"
    user.preferences = {}

    auth = AuthContext(user_id="user-abc", auth_type="jwt")
    _setup_overrides(auth, user)

    payload = {
        "star_rating": "5 stars",
        "location_preference": "city center",
        "board_type": "Full Board",
        "smoking": "non-smoking",
        "floor_preference": "high floor",
        "budget_range": "€150-250/night",
    }

    try:
        async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
            response = await client.put(
                "/api/v1/users/user-abc/preferences",
                json=payload,
            )
        assert response.status_code == 200
        assert response.json()["preferences"] == payload
    finally:
        app.dependency_overrides.clear()
