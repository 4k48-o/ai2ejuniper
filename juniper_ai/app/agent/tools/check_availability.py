"""Hotel availability check tool.

This tool is **SOAP-only** (HotelCheckAvail). Local static cache is not used:
rate plans and prices must come from Juniper live responses.
"""

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
async def check_availability(rate_plan_code: str) -> str:
    """Check if a specific hotel room is still available and confirm the price.

    Args:
        rate_plan_code: The rate plan code from the search results (e.g., "RPC_001_DBL_BB")

    Returns:
        Availability status and current price.
    """
    logger.info("Tool check_availability called with args: rate_plan_code=%s", rate_plan_code)
    client = get_juniper_client()
    try:
        result = await client.hotel_check_avail(rate_plan_code)
        return (
            f"Available: {result['available']}\n"
            f"Price: {result['total_price']} {result['currency']}\n"
            f"Rate Plan: {result['rate_plan_code']}"
        )
    except SOAPTimeoutError:
        return "Hotel booking service is temporarily unavailable. Please try again in a moment."
    except RoomUnavailableError:
        return "This room is no longer available. Let me search for alternatives."
    except PriceChangedError as e:
        msg = f"The price has changed from {e.old_price} to {e.new_price} {e.currency}."
        if e.new_rate_plan_code:
            # Juniper docs: callers must continue the booking flow with the
            # *new* RatePlanCode once warnPriceChanged is raised.
            msg += f" Updated rate plan: {e.new_rate_plan_code}."
        return msg + " Would you like to proceed with the new price?"
    except NoResultsError:
        return "No hotels found for your search criteria. Try different dates or destination."
    except JuniperFaultError as e:
        return f"The booking system returned an error: {e}"
    except BookingPendingError:
        return "Your booking is being processed. Please wait a moment."
    except Exception:
        logger.error("Unexpected error in check_availability", exc_info=True)
        raise
