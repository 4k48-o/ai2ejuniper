"""Cancel fee estimation tool — query cancellation costs without actually cancelling."""

import logging

from langchain_core.tools import tool

from juniper_ai.app.agent.tools._user_context import get_current_user_id
from juniper_ai.app.juniper.exceptions import (
    BookingOwnershipError,
    SOAPTimeoutError,
    JuniperFaultError,
)
from juniper_ai.app.juniper.mock_client import get_juniper_client

logger = logging.getLogger(__name__)


@tool
async def estimate_cancellation_fees(booking_id: str) -> str:
    """Query the cancellation fees for a booking WITHOUT actually cancelling it.

    Always call this before cancel_booking so the user knows the cost.

    Args:
        booking_id: The Juniper booking ID to check

    Returns:
        Cancellation cost amount and currency, or free cancellation notice.
    """
    user_id = get_current_user_id()
    logger.info("Tool estimate_cancellation_fees called: booking_id=%s, user_id=%s", booking_id, user_id)
    client = get_juniper_client()
    try:
        result = await client.cancel_booking(booking_id, user_id=user_id, only_fees=True)

        cost = result.get("cancel_cost", "0")
        currency = result.get("cancel_cost_currency", "EUR")
        warnings = result.get("warnings", [])

        if "warnCancellationNotCalculated" in warnings:
            return (
                f"Cancellation fees for booking {booking_id} could not be calculated. "
                f"Please contact your supplier for details before cancelling."
            )

        cost_float = float(cost) if cost else 0
        if cost_float == 0:
            return f"Booking {booking_id} can be cancelled for FREE (no cancellation charges)."

        return (
            f"Cancellation fees for booking {booking_id}: {cost} {currency}\n"
            f"If you proceed with cancellation, this amount will be charged.\n"
            f"Would you like to proceed?"
        )
    except BookingOwnershipError:
        return "This booking does not belong to you."
    except SOAPTimeoutError:
        return "Hotel booking service is temporarily unavailable. Please try again in a moment."
    except JuniperFaultError as e:
        return f"The booking system returned an error: {e}"
    except Exception:
        logger.error("Unexpected error in estimate_cancellation_fees", exc_info=True)
        raise
