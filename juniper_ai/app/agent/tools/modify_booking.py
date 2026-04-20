"""Modify booking tool — Step 1: request modification options."""

import json
import logging

from langchain_core.tools import tool

from juniper_ai.app.agent.tools._user_context import get_current_user_id
from juniper_ai.app.juniper.exceptions import (
    BookingOwnershipError,
    SOAPTimeoutError,
    JuniperFaultError,
    RoomUnavailableError,
    PriceChangedError,
    BookingPendingError,
    NoResultsError,
)
from juniper_ai.app.juniper.mock_client import get_juniper_client

logger = logging.getLogger(__name__)


@tool
async def modify_booking(
    booking_id: str,
    new_check_in: str | None = None,
    new_check_out: str | None = None,
) -> str:
    """Request a modification for an existing hotel booking (Step 1 of 2).

    This returns a modification preview with a ModifyCode. The user must
    confirm the changes before calling confirm_modify with the ModifyCode.

    Args:
        booking_id: The Juniper booking ID to modify
        new_check_in: New check-in date in YYYY-MM-DD format (optional)
        new_check_out: New check-out date in YYYY-MM-DD format (optional)

    Returns:
        Modification preview with ModifyCode. User must confirm to apply.
    """
    user_id = get_current_user_id()
    logger.info(
        "Tool modify_booking called: booking_id=%s, new_check_in=%s, new_check_out=%s, user_id=%s",
        booking_id, new_check_in, new_check_out, user_id,
    )
    client = get_juniper_client()
    modifications = {}
    if new_check_in:
        modifications["check_in"] = new_check_in
    if new_check_out:
        modifications["check_out"] = new_check_out

    try:
        result = await client.hotel_modify(booking_id, user_id=user_id, **modifications)

        modify_code = result.get("modify_code", "")
        response = (
            f"Modification Preview:\n"
            f"Booking ID: {result.get('booking_id', booking_id)}\n"
            f"Status: {result.get('status', 'modification_pending')}\n"
            f"Check-in: {result.get('check_in', 'N/A')}\n"
            f"Check-out: {result.get('check_out', 'N/A')}\n"
            f"ModifyCode: {modify_code}\n\n"
            f"Please ask the user to confirm this modification. "
            f"If confirmed, call confirm_modify with ModifyCode: {modify_code}"
        )
        return response
    except BookingOwnershipError:
        return "This booking does not belong to you. You can only modify your own bookings."
    except SOAPTimeoutError:
        return "Hotel booking service is temporarily unavailable. Please try again in a moment."
    except RoomUnavailableError:
        return "This room is no longer available. Let me search for alternatives."
    except PriceChangedError as e:
        return f"The price has changed from {e.old_price} to {e.new_price}. Would you like to proceed with the new price?"
    except NoResultsError:
        return "No hotels found for your search criteria. Try different dates or destination."
    except JuniperFaultError as e:
        return f"The booking system returned an error: {e}"
    except BookingPendingError:
        return "Your booking is being processed. Please wait a moment."
    except Exception:
        logger.error("Unexpected error in modify_booking", exc_info=True)
        raise
