"""User lookup / creation for API and smoke scripts."""

from __future__ import annotations

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from juniper_ai.app.db.models import User


async def get_or_create_user_by_external_id(db: AsyncSession, external_id: str) -> User:
    """Return the user row for ``external_id``, inserting a stub row if needed."""
    result = await db.execute(select(User).where(User.external_id == external_id))
    user = result.scalar_one_or_none()
    if not user:
        user = User(external_id=external_id, preferences={})
        db.add(user)
        await db.flush()
    return user
