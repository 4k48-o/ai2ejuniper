"""Booking rules validation tool."""

import logging

from langchain_core.tools import tool

from juniper_ai.app.juniper.exceptions import (
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
async def get_booking_rules(rate_plan_code: str) -> str:
    """Get the booking rules and cancellation policy for a hotel room before booking.

    This returns a BookingCode with an expiration time. The booking must be
    completed before the BookingCode expires. If it expires, call this tool
    again to get a new BookingCode.

    Args:
        rate_plan_code: The rate plan code from the search results

    Returns:
        Booking rules, cancellation policy, final price, and BookingCode expiry.
    """
    logger.info("Tool get_booking_rules called with args: rate_plan_code=%s", rate_plan_code)
    client = get_juniper_client()
    try:
        rules = await client.hotel_booking_rules(rate_plan_code)

        lines = [
            f"Valid: {rules['valid']}",
            f"Final Price: {rules['total_price']} {rules['currency']}",
            f"Cancellation Policy: {rules['cancellation_policy']}",
            f"Remarks: {rules['remarks'] or 'None'}",
        ]

        if rules.get("booking_code"):
            lines.append(f"BookingCode: {rules['booking_code']}")
        if rules.get("booking_code_expires_at"):
            lines.append(f"BookingCode Expires: {rules['booking_code_expires_at']}")
            lines.append("IMPORTANT: Complete the booking before the BookingCode expires.")

        return "\n".join(lines)
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
        logger.error("Unexpected error in get_booking_rules", exc_info=True)
        raise
