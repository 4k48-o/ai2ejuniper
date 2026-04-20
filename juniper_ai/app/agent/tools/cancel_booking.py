"""Cancel booking tool."""

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
async def cancel_booking(booking_id: str) -> str:
    """Cancel an existing hotel booking. Only call after user has confirmed cancellation.

    Args:
        booking_id: The Juniper booking ID to cancel

    Returns:
        Cancellation confirmation.
    """
    user_id = get_current_user_id()
    logger.info("Tool cancel_booking called with args: booking_id=%s, user_id=%s", booking_id, user_id)
    client = get_juniper_client()
    try:
        result = await client.cancel_booking(booking_id, user_id=user_id)
        event_data = {
            "__booking_event__": True,
            "event_type": "booking.cancelled",
            "booking_id": result["booking_id"],
            "status": result.get("status"),
        }
        confirmation = f"Booking {result['booking_id']} has been cancelled. Status: {result['status']}"
        return f"{confirmation}\n\n__BOOKING_EVENT__{json.dumps(event_data)}__END_BOOKING_EVENT__"
    except BookingOwnershipError:
        return "This booking does not belong to you. You can only cancel your own bookings."
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
        logger.error("Unexpected error in cancel_booking", exc_info=True)
        raise
