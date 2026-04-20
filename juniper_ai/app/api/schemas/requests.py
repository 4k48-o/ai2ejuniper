"""API request schemas."""

from pydantic import BaseModel, Field


class CreateConversationRequest(BaseModel):
    external_user_id: str = Field(..., description="External user identifier from the integrating platform")


class SendMessageRequest(BaseModel):
    content: str = Field(..., min_length=1, max_length=5000, description="User message content")


class UpdatePreferencesRequest(BaseModel):
    star_rating: str | None = Field(None, max_length=50, description="Preferred star rating (e.g., '4 stars')")
    location_preference: str | None = Field(None, max_length=255, description="Location preference (e.g., 'central')")
    board_type: str | None = Field(None, max_length=100, description="Board type (e.g., 'Bed & Breakfast')")
    smoking: str | None = Field(None, max_length=20, description="Smoking preference (e.g., 'non-smoking')")
    floor_preference: str | None = Field(None, max_length=50, description="Floor preference (e.g., 'high floor')")
    budget_range: str | None = Field(None, max_length=100, description="Budget range (e.g., '€150-250/night')")


class RegisterWebhookRequest(BaseModel):
    url: str = Field(..., description="Webhook callback URL")
    events: list[str] = Field(
        ...,
        description="Event types to subscribe to",
        examples=[["booking.confirmed", "booking.cancelled"]],
    )
    secret: str = Field(..., description="Shared secret for HMAC-SHA256 signing (minimum 16 characters)")
