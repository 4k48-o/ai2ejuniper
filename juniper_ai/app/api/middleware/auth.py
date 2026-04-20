"""Authentication middleware: JWT Bearer + API Key."""

import logging
from dataclasses import dataclass, field

from fastapi import Depends, HTTPException, Request, Security
from jose import JWTError, jwt
from fastapi.security import APIKeyHeader, HTTPAuthorizationCredentials, HTTPBearer

from juniper_ai.app.config import settings

logger = logging.getLogger(__name__)

bearer_scheme = HTTPBearer(auto_error=False)
api_key_header = APIKeyHeader(name="X-API-Key", auto_error=False)


@dataclass
class AuthContext:
    """Authenticated user context."""

    user_id: str  # external_id from JWT or API key subject
    auth_type: str  # "jwt" or "api_key"
    external_user_id: str | None = field(default=None)  # from X-External-User-Id header (API key auth)


async def get_auth_context(
    request: Request,
    credentials: HTTPAuthorizationCredentials | None = Security(bearer_scheme),
    api_key: str | None = Security(api_key_header),
) -> AuthContext:
    """Authenticate via JWT Bearer token or API Key."""

    # Try JWT first
    if credentials:
        token = (credentials.credentials or "").strip()
        if not token:
            raise HTTPException(status_code=401, detail="Invalid token: empty Bearer token")
        try:
            payload = jwt.decode(
                token,
                settings.jwt_secret_key,
                algorithms=["HS256"],
            )
            user_id = payload.get("sub")
            if not user_id:
                raise HTTPException(status_code=401, detail="Invalid token: missing sub claim")
            return AuthContext(user_id=user_id, auth_type="jwt")
        except HTTPException:
            raise
        except JWTError as e:
            logger.warning("JWT auth failed: %s", e)
            raise HTTPException(status_code=401, detail="Invalid or expired token") from e

    # Try API Key
    if api_key and api_key in settings.api_keys_list:
        external_user_id = request.headers.get("X-External-User-Id")
        user_id = external_user_id if external_user_id else f"apikey:{api_key[:8]}"
        return AuthContext(
            user_id=user_id,
            auth_type="api_key",
            external_user_id=external_user_id,
        )

    raise HTTPException(
        status_code=401,
        detail="Authentication required. Provide a Bearer token or X-API-Key header.",
    )
