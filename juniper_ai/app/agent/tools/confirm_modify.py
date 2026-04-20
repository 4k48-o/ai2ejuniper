"""Confirm booking modification tool — Step 2: apply the modification."""

import json
import logging

from langchain_core.tools import tool

from juniper_ai.app.juniper.exceptions import (
    SOAPTimeoutError,
    JuniperFaultError,
    BookingPendingError,
)
from juniper_ai.app.juniper.mock_client import get_juniper_client

logger = logging.getLogger(__name__)


@tool
async def confirm_modify(modify_code: str, booking_id: str) -> str:
    """Confirm a previously requested booking modification (Step 2 of 2).

    Only call this after the user has reviewed and approved the modification
    preview from modify_booking.

    Args:
        modify_code: The ModifyCode returned by modify_booking
        booking_id: The original booking ID being modified

    Returns:
        Confirmation of the applied modification.
    """
    logger.info("Tool confirm_modify called: modify_code=%s, booking_id=%s", modify_code, booking_id)
    client = get_juniper_client()
    try:
        result = await client.hotel_confirm_modify(modify_code)

        event_data = {
            "__booking_event__": True,
            "event_type": "booking.modified",
            "booking_id": booking_id,
            "status": result.get("status", "modified"),
            "check_in": result.get("check_in"),
            "check_out": result.get("check_out"),
        }
        response = (
            f"Booking Modified!\n"
            f"Booking ID: {booking_id}\n"
            f"Status: {result.get('status', 'modified')}"
        )
        return f"{response}\n\n__BOOKING_EVENT__{json.dumps(event_data)}__END_BOOKING_EVENT__"
    except SOAPTimeoutError:
        return "Hotel booking service is temporarily unavailable. Please try again in a moment."
    except JuniperFaultError as e:
        return f"The booking system returned an error: {e}"
    except BookingPendingError:
        return "The modification is being processed. Please wait a moment."
    except Exception:
        logger.error("Unexpected error in confirm_modify", exc_info=True)
        raise
