"""Webhook event dispatcher with HMAC signing and retry logic."""

import hashlib
import hmac
import json
import logging
from datetime import datetime, timezone

import httpx
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from juniper_ai.app.db.models import WebhookSubscription

logger = logging.getLogger(__name__)

RETRY_DELAYS = [30, 60, 120]  # seconds
MAX_CONSECUTIVE_FAILURES = 3


def _sign_payload(payload: str, secret: str) -> str:
    """Generate HMAC-SHA256 signature for the payload."""
    return hmac.new(secret.encode(), payload.encode(), hashlib.sha256).hexdigest()


async def dispatch_event(
    db: AsyncSession,
    event_type: str,
    booking_id: str,
    booking_details: dict,
) -> None:
    """Dispatch a webhook event to all matching subscribers."""
    result = await db.execute(
        select(WebhookSubscription).where(
            WebhookSubscription.active == True,
        )
    )
    subscriptions = result.scalars().all()

    for sub in subscriptions:
        if event_type not in sub.events:
            continue

        payload = json.dumps({
            "event_type": event_type,
            "booking_id": booking_id,
            "timestamp": datetime.now(timezone.utc).isoformat(),
            "booking_details": booking_details,
        })

        signature = _sign_payload(payload, sub.secret)
        headers = {
            "Content-Type": "application/json",
            "X-Webhook-Signature": f"sha256={signature}",
            "X-Event-Type": event_type,
        }

        success = await _deliver_with_retry(sub.url, payload, headers)

        if not success:
            sub.failure_count += 1
            if sub.failure_count >= MAX_CONSECUTIVE_FAILURES:
                sub.active = False
                logger.warning("Webhook %s deactivated after %d failures", sub.id, sub.failure_count)
        else:
            sub.failure_count = 0

    await db.flush()


async def _deliver_with_retry(url: str, payload: str, headers: dict) -> bool:
    """Attempt to deliver a webhook with retries."""
    import asyncio

    async with httpx.AsyncClient(timeout=10) as client:
        for attempt in range(len(RETRY_DELAYS) + 1):
            try:
                response = await client.post(url, content=payload, headers=headers)
                if response.status_code < 300:
                    logger.info("Webhook delivered to %s (attempt %d)", url, attempt + 1)
                    return True
                logger.warning(
                    "Webhook delivery to %s failed with status %d (attempt %d)",
                    url, response.status_code, attempt + 1,
                )
            except Exception as e:
                logger.warning("Webhook delivery to %s failed: %s (attempt %d)", url, e, attempt + 1)

            if attempt < len(RETRY_DELAYS):
                await asyncio.sleep(RETRY_DELAYS[attempt])

    logger.error("Webhook delivery to %s exhausted all retries", url)
    return False
