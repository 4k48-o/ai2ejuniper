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
async def get_booking_rules(
    rate_plan_code: str,
    check_in: str | None = None,
    check_out: str | None = None,
    hotel_code: str | None = None,
    expected_price: str | None = None,
) -> str:
    """Get the booking rules and cancellation policy for a hotel room before booking.

    This returns a BookingCode with an expiration time (~10 minutes). The
    booking must be completed before the BookingCode expires. If it
    expires, call this tool again to get a new BookingCode.

    When called with ``check_in`` / ``check_out`` / ``hotel_code`` (highly
    recommended — obtain them from the upstream search result), Juniper
    cross-checks the RatePlanCode against those values and will return a
    clear ``warnCheckNotPossible`` instead of a confusing partial response
    if something drifted.

    Args:
        rate_plan_code: The rate plan code from the search / check-avail step.
        check_in: Check-in date (YYYY-MM-DD) — from the upstream search.
        check_out: Check-out date (YYYY-MM-DD).
        hotel_code: JPCode of the selected hotel.
        expected_price: Previous total (used to describe a price change to the user).

    Returns:
        Booking rules, cancellation policy, final price, and BookingCode expiry.
    """
    logger.info(
        "Tool get_booking_rules called: rate_plan_code=%s, hotel_code=%s, %s→%s",
        rate_plan_code, hotel_code, check_in, check_out,
    )
    client = get_juniper_client()
    try:
        rules = await client.hotel_booking_rules(
            rate_plan_code,
            check_in=check_in,
            check_out=check_out,
            hotel_code=hotel_code,
            expected_price=expected_price,
        )

        lines = [
            f"Valid: {rules['valid']}",
            f"Final Price: {rules['total_price']} {rules['currency']}",
            f"Cancellation Policy: {rules['cancellation_policy'] or 'non-refundable (no policy returned)'}",
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
        msg = f"The price has changed from {e.old_price} to {e.new_price} {e.currency}."
        if getattr(e, "new_rate_plan_code", ""):
            msg += f" I'll use the updated rate code ({e.new_rate_plan_code}) — please confirm to proceed."
        else:
            msg += " Would you like to proceed with the new price?"
        return msg
    except NoResultsError:
        return "No hotels found for your search criteria. Try different dates or destination."
    except JuniperFaultError as e:
        return f"The booking system returned an error: {e}"
    except BookingPendingError:
        return "Your booking is being processed. Please wait a moment."
    except Exception:
        logger.error("Unexpected error in get_booking_rules", exc_info=True)
        raise
