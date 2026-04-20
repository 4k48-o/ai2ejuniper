"""User preferences endpoints."""

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from juniper_ai.app.api.middleware.auth import AuthContext, get_auth_context
from juniper_ai.app.api.schemas.requests import UpdatePreferencesRequest
from juniper_ai.app.api.schemas.responses import PreferencesResponse
from juniper_ai.app.db.models import User
from juniper_ai.app.db.session import get_db

router = APIRouter()


def _verify_ownership(auth: AuthContext, user_external_id: str) -> None:
    """Verify the authenticated user owns the requested resource."""
    if auth.auth_type == "jwt":
        if auth.user_id != user_external_id:
            raise HTTPException(status_code=403, detail="Access denied: user mismatch")
    elif auth.auth_type == "api_key":
        if not auth.external_user_id:
            raise HTTPException(
                status_code=400,
                detail="X-External-User-Id header is required for API key authentication",
            )
        if auth.external_user_id != user_external_id:
            raise HTTPException(status_code=403, detail="Access denied: user mismatch")


@router.get("/users/{user_external_id}/preferences", response_model=PreferencesResponse)
async def get_preferences(
    user_external_id: str,
    auth: AuthContext = Depends(get_auth_context),
    db: AsyncSession = Depends(get_db),
):
    """Get user preferences."""
    _verify_ownership(auth, user_external_id)

    result = await db.execute(select(User).where(User.external_id == user_external_id))
    user = result.scalar_one_or_none()
    if not user:
        raise HTTPException(status_code=404, detail="User not found")

    return PreferencesResponse(user_id=user.id, preferences=user.preferences or {})


@router.put("/users/{user_external_id}/preferences", response_model=PreferencesResponse)
async def update_preferences(
    user_external_id: str,
    request: UpdatePreferencesRequest,
    auth: AuthContext = Depends(get_auth_context),
    db: AsyncSession = Depends(get_db),
):
    """Update user preferences."""
    _verify_ownership(auth, user_external_id)

    result = await db.execute(select(User).where(User.external_id == user_external_id))
    user = result.scalar_one_or_none()
    if not user:
        raise HTTPException(status_code=404, detail="User not found")

    # Merge new preferences with existing ones
    current = user.preferences or {}
    updates = request.model_dump(exclude_none=True)
    current.update(updates)
    user.preferences = current

    await db.flush()

    return PreferencesResponse(user_id=user.id, preferences=user.preferences)
