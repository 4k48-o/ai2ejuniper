"""Webhook management endpoints."""

import uuid
from ipaddress import ip_address
from urllib.parse import urlparse

from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from juniper_ai.app.api.middleware.auth import AuthContext, get_auth_context
from juniper_ai.app.api.schemas.requests import RegisterWebhookRequest
from juniper_ai.app.api.schemas.responses import WebhookResponse
from juniper_ai.app.db.models import WebhookSubscription
from juniper_ai.app.db.session import get_db

router = APIRouter()

VALID_EVENTS = {"booking.confirmed", "booking.cancelled", "booking.modified"}

# SSRF protection: block private/internal IPs
BLOCKED_HOSTS = {"localhost", "127.0.0.1", "0.0.0.0", "::1"}


def _validate_webhook_url(url: str) -> None:
    """Validate webhook URL for SSRF protection."""
    parsed = urlparse(url)
    if parsed.scheme not in ("https",):
        raise HTTPException(status_code=400, detail="Webhook URL must use HTTPS")
    hostname = parsed.hostname or ""
    if hostname in BLOCKED_HOSTS:
        raise HTTPException(status_code=400, detail="Invalid webhook URL: internal addresses not allowed")
    try:
        ip = ip_address(hostname)
        if ip.is_private or ip.is_loopback or ip.is_reserved:
            raise HTTPException(status_code=400, detail="Invalid webhook URL: private IP addresses not allowed")
    except ValueError:
        pass  # hostname is not an IP, that's fine


@router.post("/webhooks", response_model=WebhookResponse, status_code=status.HTTP_201_CREATED)
async def register_webhook(
    request: RegisterWebhookRequest,
    auth: AuthContext = Depends(get_auth_context),
    db: AsyncSession = Depends(get_db),
):
    """Register a new webhook subscription."""
    if auth.auth_type != "api_key":
        raise HTTPException(status_code=403, detail="Webhook management requires API key authentication")

    _validate_webhook_url(request.url)

    if len(request.secret) < 16:
        raise HTTPException(
            status_code=400,
            detail="Webhook secret must be at least 16 characters",
        )

    invalid_events = set(request.events) - VALID_EVENTS
    if invalid_events:
        raise HTTPException(
            status_code=400,
            detail=f"Invalid events: {invalid_events}. Valid: {VALID_EVENTS}",
        )

    webhook = WebhookSubscription(
        url=request.url,
        events=request.events,
        secret=request.secret,
        active=True,
    )
    db.add(webhook)
    await db.flush()

    return WebhookResponse(
        id=webhook.id,
        url=webhook.url,
        events=webhook.events,
        active=webhook.active,
        created_at=webhook.created_at,
    )


@router.get("/webhooks", response_model=list[WebhookResponse])
async def list_webhooks(
    auth: AuthContext = Depends(get_auth_context),
    db: AsyncSession = Depends(get_db),
):
    """List all webhook subscriptions."""
    if auth.auth_type != "api_key":
        raise HTTPException(status_code=403, detail="Webhook management requires API key authentication")

    result = await db.execute(select(WebhookSubscription).order_by(WebhookSubscription.created_at.desc()))
    webhooks = result.scalars().all()
    return [
        WebhookResponse(
            id=w.id, url=w.url, events=w.events, active=w.active, created_at=w.created_at,
        )
        for w in webhooks
    ]


@router.delete("/webhooks/{webhook_id}")
async def delete_webhook(
    webhook_id: uuid.UUID,
    auth: AuthContext = Depends(get_auth_context),
    db: AsyncSession = Depends(get_db),
):
    """Delete a webhook subscription."""
    if auth.auth_type != "api_key":
        raise HTTPException(status_code=403, detail="Webhook management requires API key authentication")

    result = await db.execute(select(WebhookSubscription).where(WebhookSubscription.id == webhook_id))
    webhook = result.scalar_one_or_none()
    if not webhook:
        raise HTTPException(status_code=404, detail="Webhook not found")

    await db.delete(webhook)
    return {"status": "deleted"}
