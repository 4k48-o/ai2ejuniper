"""In-memory sliding-window rate limiter (single-process)."""

import logging
import time
from collections import defaultdict

from fastapi import Depends, HTTPException, Request
from fastapi.responses import JSONResponse

from juniper_ai.app.api.middleware.auth import AuthContext, get_auth_context
from juniper_ai.app.config import settings

logger = logging.getLogger(__name__)

# user_id -> list of request timestamps (epoch seconds)
_request_log: dict[str, list[float]] = defaultdict(list)
_last_cleanup: float = 0.0

WINDOW_SECONDS = 60
CLEANUP_INTERVAL = 300  # purge stale entries every 5 minutes


def _cleanup_if_needed() -> None:
    """Remove entries older than the window for all users, periodically."""
    global _last_cleanup
    now = time.monotonic()
    if now - _last_cleanup < CLEANUP_INTERVAL:
        return
    _last_cleanup = now
    cutoff = time.monotonic() - WINDOW_SECONDS
    stale_keys = []
    for uid, timestamps in _request_log.items():
        _request_log[uid] = [t for t in timestamps if t > cutoff]
        if not _request_log[uid]:
            stale_keys.append(uid)
    for key in stale_keys:
        del _request_log[key]


def _get_limit(auth: AuthContext) -> int:
    if auth.auth_type == "api_key":
        return settings.rate_limit_api_key
    return settings.rate_limit_user


async def check_rate_limit(
    request: Request,
    auth: AuthContext = Depends(get_auth_context),
) -> AuthContext:
    """FastAPI dependency that enforces per-user rate limits.

    Returns the AuthContext so downstream dependencies can reuse it
    without re-authenticating.  Raises 429 when the limit is exceeded.
    """
    _cleanup_if_needed()

    now = time.monotonic()
    limit = _get_limit(auth)
    uid = auth.user_id

    # Trim timestamps outside the current window
    cutoff = now - WINDOW_SECONDS
    timestamps = _request_log[uid]
    _request_log[uid] = timestamps = [t for t in timestamps if t > cutoff]

    if len(timestamps) >= limit:
        # Earliest expiry determines Retry-After
        retry_after = int(timestamps[0] - cutoff) + 1
        logger.warning(
            "Rate limit exceeded for user=%s (type=%s, limit=%d/min)",
            uid,
            auth.auth_type,
            limit,
        )
        raise HTTPException(
            status_code=429,
            detail="Rate limit exceeded. Try again later.",
            headers={"Retry-After": str(retry_after)},
        )

    timestamps.append(now)
    return auth
