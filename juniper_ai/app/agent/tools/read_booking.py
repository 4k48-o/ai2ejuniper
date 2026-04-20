"""Read booking tool — queries the local database, not the supplier API."""

import logging

from langchain_core.tools import tool
from sqlalchemy import select

from juniper_ai.app.agent.tools._booking_display import guest_name_email_from_details
from juniper_ai.app.agent.tools._user_context import get_current_user_uuid
from juniper_ai.app.db.models import Booking
from juniper_ai.app.db.session import async_session

logger = logging.getLogger(__name__)


@tool
async def read_booking(booking_id: str) -> str:
    """Look up an existing hotel booking by its booking ID.

    Args:
        booking_id: The Juniper booking ID (e.g., "JNP-XXXXXXXX")

    Returns:
        Booking details including status, hotel, guest name/email, dates, and price.
    """
    uid = get_current_user_uuid()
    logger.info("Tool read_booking called with args: booking_id=%s, user_id=%s", booking_id, uid)

    if not uid:
        return "Unable to identify the current user. Please try again."

    async with async_session() as db:
        result = await db.execute(
            select(Booking).where(
                Booking.juniper_booking_id == booking_id,
                Booking.user_id == uid,
            )
        )
        booking = result.scalar_one_or_none()

    if not booking:
        return "Booking not found or it does not belong to you."

    guest_name, guest_email = guest_name_email_from_details(booking.booking_details)
    return (
        f"Booking ID: {booking.juniper_booking_id}\n"
        f"Status: {booking.status.value}\n"
        f"Hotel: {booking.hotel_name}\n"
        f"Guest: {guest_name}\n"
        f"Email: {guest_email}\n"
        f"Check-in: {booking.check_in}\n"
        f"Check-out: {booking.check_out}\n"
        f"Total: {booking.total_price} {booking.currency}"
    )
