"""API response schemas."""

from datetime import datetime
from typing import Any
from uuid import UUID

from pydantic import BaseModel


class MessageResponse(BaseModel):
    """Mixed response format: text + structured data."""

    text: str
    data: dict[str, Any] | None = None
    status: str  # idle, searching, selecting, confirming, booking, completed, managing


class ConversationResponse(BaseModel):
    id: UUID
    user_id: UUID
    status: str
    language: str | None
    created_at: datetime


class BookingResponse(BaseModel):
    id: UUID
    juniper_booking_id: str | None
    status: str
    hotel_name: str | None
    check_in: str | None
    check_out: str | None
    total_price: str | None
    currency: str | None
    created_at: datetime


class PreferencesResponse(BaseModel):
    user_id: UUID
    preferences: dict[str, Any]


class WebhookResponse(BaseModel):
    id: UUID
    url: str
    events: list[str]
    active: bool
    created_at: datetime


class HealthResponse(BaseModel):
    status: str
    version: str
    environment: str
