"""List bookings tool — queries the local database, not the supplier API."""

import logging

from langchain_core.tools import tool
from sqlalchemy import select

from juniper_ai.app.agent.tools._booking_display import guest_name_email_from_details
from juniper_ai.app.agent.tools._user_context import get_current_user_uuid
from juniper_ai.app.db.models import Booking
from juniper_ai.app.db.session import async_session

logger = logging.getLogger(__name__)


@tool
async def list_bookings() -> str:
    """List all hotel bookings for the current user.

    Use this when the user asks about their booking history, past reservations,
    or wants to see all their bookings.

    Returns:
        A summary of all bookings including booking ID, hotel, guest name/email (from
        stored booking details), dates, price, and status.
    """
    uid = get_current_user_uuid()
    logger.info("Tool list_bookings called, user_id=%s", uid)

    if not uid:
        return "Unable to identify the current user. Please try again."

    async with async_session() as db:
        result = await db.execute(
            select(Booking).where(Booking.user_id == uid)
            .order_by(Booking.created_at.desc())
        )
        bookings = result.scalars().all()

    if not bookings:
        return "No bookings found. The user has no booking history."

    lines = [f"Found {len(bookings)} booking(s):\n"]
    for b in bookings:
        guest_name, guest_email = guest_name_email_from_details(b.booking_details)
        lines.append(
            f"- Booking ID: {b.juniper_booking_id}\n"
            f"  Hotel: {b.hotel_name or 'N/A'}\n"
            f"  Guest: {guest_name}\n"
            f"  Email: {guest_email}\n"
            f"  Check-in: {b.check_in or 'N/A'}\n"
            f"  Check-out: {b.check_out or 'N/A'}\n"
            f"  Total: {b.total_price or 'N/A'} {b.currency or ''}\n"
            f"  Status: {b.status.value}"
        )
    return "\n".join(lines)
