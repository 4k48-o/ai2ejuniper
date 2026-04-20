"""Shared helper for extracting current user context from LangGraph runtime config."""

import uuid

from langchain_core.runnables import ensure_config


def get_current_user_id() -> str | None:
    """Extract user_id string from the current LangGraph runtime config."""
    config = ensure_config()
    return config.get("configurable", {}).get("user_id")


def get_current_user_uuid() -> uuid.UUID | None:
    """Extract user_id as UUID from the current LangGraph runtime config.

    Returns None if user_id is missing or not a valid UUID.
    """
    user_id = get_current_user_id()
    if not user_id:
        return None
    try:
        return uuid.UUID(user_id)
    except ValueError:
        return None
