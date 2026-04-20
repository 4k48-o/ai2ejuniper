"""Tests for the sliding-window rate limiter."""

import time
from unittest.mock import MagicMock, patch

import pytest
from fastapi import HTTPException

from juniper_ai.app.api.middleware.auth import AuthContext
from juniper_ai.app.api.middleware import rate_limit as rl_module
from juniper_ai.app.main import app


@pytest.fixture(autouse=True)
def _clear_rate_limit_state():
    """Reset the module-level rate limit state before each test."""
    rl_module._request_log.clear()
    rl_module._last_cleanup = 0.0
    yield
    rl_module._request_log.clear()
    rl_module._last_cleanup = 0.0


def _mock_request():
    req = MagicMock()
    return req


@pytest.mark.asyncio
async def test_requests_within_limit_pass():
    auth = AuthContext(user_id="user-1", auth_type="jwt")

    # Default rate_limit_user is 60/min. Do a few requests.
    for _ in range(5):
        result = await rl_module.check_rate_limit(
            request=_mock_request(),
            auth=auth,
        )
        assert result.user_id == "user-1"


@pytest.mark.asyncio
async def test_requests_exceeding_limit_return_429():
    auth = AuthContext(user_id="user-2", auth_type="jwt")

    # Set a very low limit for testing
    with patch.object(rl_module.settings, "rate_limit_user", 3):
        for _ in range(3):
            await rl_module.check_rate_limit(
                request=_mock_request(),
                auth=auth,
            )

        # 4th request should be rejected
        with pytest.raises(HTTPException) as exc_info:
            await rl_module.check_rate_limit(
                request=_mock_request(),
                auth=auth,
            )
        assert exc_info.value.status_code == 429
        assert "Rate limit exceeded" in exc_info.value.detail
        assert exc_info.value.headers is not None
        assert "Retry-After" in exc_info.value.headers
        retry_after = int(exc_info.value.headers["Retry-After"])
        assert 1 <= retry_after <= rl_module.WINDOW_SECONDS + 1


@pytest.mark.asyncio
async def test_rate_limits_are_independent_per_user():
    """RATE-05: exhausting one user_id does not block another."""
    auth_a = AuthContext(user_id="iso-user-a", auth_type="jwt")
    auth_b = AuthContext(user_id="iso-user-b", auth_type="jwt")

    with patch.object(rl_module.settings, "rate_limit_user", 2):
        await rl_module.check_rate_limit(_mock_request(), auth_a)
        await rl_module.check_rate_limit(_mock_request(), auth_a)
        with pytest.raises(HTTPException):
            await rl_module.check_rate_limit(_mock_request(), auth_a)

        result = await rl_module.check_rate_limit(_mock_request(), auth_b)
        assert result.user_id == "iso-user-b"


@pytest.mark.asyncio
async def test_rate_limits_reset_after_window():
    auth = AuthContext(user_id="user-3", auth_type="jwt")

    with patch.object(rl_module.settings, "rate_limit_user", 2):
        # Use up the limit
        for _ in range(2):
            await rl_module.check_rate_limit(
                request=_mock_request(),
                auth=auth,
            )

        # Simulate all timestamps being older than the window
        old_time = time.monotonic() - rl_module.WINDOW_SECONDS - 1
        rl_module._request_log["user-3"] = [old_time, old_time]

        # Should pass now since old timestamps are outside the window
        result = await rl_module.check_rate_limit(
            request=_mock_request(),
            auth=auth,
        )
        assert result.user_id == "user-3"


@pytest.mark.asyncio
async def test_api_key_uses_higher_limit():
    auth = AuthContext(user_id="apikey:testkey1", auth_type="api_key")

    with patch.object(rl_module.settings, "rate_limit_api_key", 5), \
         patch.object(rl_module.settings, "rate_limit_user", 2):
        # Should allow more than 2 requests (using api_key limit of 5)
        for _ in range(4):
            result = await rl_module.check_rate_limit(
                request=_mock_request(),
                auth=auth,
            )
        assert result.auth_type == "api_key"


def test_rate_limit_dependency_is_attached_to_core_api_routes():
    from juniper_ai.app.api.middleware.rate_limit import check_rate_limit

    target_paths = {
        "/api/v1/conversations",
        "/api/v1/bookings",
        "/api/v1/users/{user_external_id}/preferences",
        "/api/v1/webhooks",
    }
    seen = set()
    for route in app.routes:
        path = getattr(route, "path", None)
        if path not in target_paths:
            continue
        deps = getattr(route, "dependant", None)
        if not deps:
            continue
        dep_calls = {d.call for d in deps.dependencies}
        assert check_rate_limit in dep_calls
        seen.add(path)

    assert seen == target_paths
