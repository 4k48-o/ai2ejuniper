"""Persist confirmed bookings to PostgreSQL.

Used by conversation routes (agent ``book_hotel`` tool output) and by
``scripts/test_juniper_sandbox.py --persist-db`` for UAT end-to-end checks.
"""

from __future__ import annotations

import logging
import uuid

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from juniper_ai.app.db.models import Booking, BookingStatus
from juniper_ai.app.webhooks.dispatcher import dispatch_event

logger = logging.getLogger(__name__)


async def persist_booking_record(
    db: AsyncSession,
    *,
    user_id: uuid.UUID,
    conversation_id: uuid.UUID,
    booking_data: dict,
) -> uuid.UUID | None:
    """Insert a ``bookings`` row with idempotency on ``conversation_id:juniper_id``.

    Returns the new row's primary key, or ``None`` if this booking was already
    stored (duplicate idempotency key).
    """
    juniper_booking_id = booking_data.get("booking_id", "")
    idempotency_key = f"{conversation_id}:{juniper_booking_id}"

    existing = await db.execute(
        select(Booking).where(Booking.idempotency_key == idempotency_key)
    )
    if existing.scalar_one_or_none() is not None:
        logger.info("Duplicate booking detected (idempotency_key=%s), skipping", idempotency_key)
        return None

    booking = Booking(
        user_id=user_id,
        conversation_id=conversation_id,
        juniper_booking_id=juniper_booking_id,
        idempotency_key=idempotency_key,
        status=BookingStatus.confirmed,
        hotel_name=booking_data.get("hotel_name"),
        check_in=booking_data.get("check_in"),
        check_out=booking_data.get("check_out"),
        total_price=booking_data.get("total_price"),
        currency=booking_data.get("currency"),
        booking_details=booking_data,
        rate_plan_code=booking_data.get("rate_plan_code"),
        country_of_residence=booking_data.get("country_of_residence"),
        external_booking_reference=booking_data.get("external_booking_reference"),
    )
    db.add(booking)
    await db.flush()

    logger.info("Persisted booking %s (juniper_id=%s)", booking.id, juniper_booking_id)

    try:
        await dispatch_event(
            db=db,
            event_type="booking.confirmed",
            booking_id=str(booking.id),
            booking_details={
                "juniper_booking_id": juniper_booking_id,
                "hotel_name": booking_data.get("hotel_name"),
                "check_in": booking_data.get("check_in"),
                "check_out": booking_data.get("check_out"),
                "total_price": booking_data.get("total_price"),
                "currency": booking_data.get("currency"),
                "guest_name": booking_data.get("guest_name"),
                "guest_email": booking_data.get("guest_email"),
            },
        )
    except Exception:
        logger.error("Failed to dispatch booking.confirmed webhook", exc_info=True)

    return booking.id
