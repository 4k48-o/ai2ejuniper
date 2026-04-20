"""Hotel search tool for LangGraph agent.

Static/SOAP cut-over:
- **PostgreSQL (L1)**: destination → zone `code` via ``get_zone_code`` / ``get_zone_candidates``
  (no SOAP).
- **Juniper SOAP**: availability and prices via ``hotel_avail`` only.
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
from juniper_ai.app.agent.tools._date_utils import validate_dates
from juniper_ai.app.db.session import async_session
from juniper_ai.app.juniper.mock_client import get_juniper_client
from juniper_ai.app.juniper.static_data import get_zone_code, get_zone_candidates

logger = logging.getLogger(__name__)


@tool
async def search_hotels(
    destination: str,
    check_in: str,
    check_out: str,
    adults: int = 2,
    children: int = 0,
    star_rating: int | None = None,
    max_price: float | None = None,
    board_type: str | None = None,
    country_of_residence: str = "ES",
) -> str:
    """Search for available hotels in a destination.

    Args:
        destination: City or destination name (e.g., "Barcelona", "Madrid")
        check_in: Check-in date in YYYY-MM-DD format
        check_out: Check-out date in YYYY-MM-DD format
        adults: Number of adult guests (default 2)
        children: Number of child guests (default 0)
        star_rating: Minimum star rating filter (e.g., 3, 4, 5). Only return hotels with this star rating.
        max_price: Maximum price per night in EUR. Only return hotels at or below this price.
        board_type: Board type filter (e.g., "Breakfast", "Half Board", "Full Board", "Room Only")
        country_of_residence: Guest country (ISO-3166-1 alpha-2 code, default "ES"). Must stay consistent across the entire booking flow.

    Returns:
        A formatted list of available hotels with prices and details.
    """
    logger.info(
        "Tool search_hotels called with args: destination=%s, check_in=%s, check_out=%s, adults=%s, children=%s, star=%s, max_price=%s, board=%s",
        destination, check_in, check_out, adults, children, star_rating, max_price, board_type,
    )
    date_error = validate_dates(check_in, check_out)
    if date_error:
        return date_error

    # Resolve destination text → zone code via local cache
    async with async_session() as db:
        zone = await get_zone_code(db, destination)

    if not zone:
        # Try to find candidates for disambiguation
        async with async_session() as db:
            candidates = await get_zone_candidates(db, destination, limit=5)
        if candidates:
            lines = [f"Could not find exact match for '{destination}'. Did you mean:"]
            for c in candidates:
                lines.append(f"  - {c['name']} ({c['area_type']})")
            return "\n".join(lines)
        # No candidates at all — fall back to passing destination as-is (for mock mode compatibility)
        zone_code = destination
        logger.warning("No zone found for '%s', using as-is", destination)
    else:
        zone_code = zone["code"]
        logger.info("Resolved '%s' → zone code %s (%s)", destination, zone_code, zone["name"])

    client = get_juniper_client()
    try:
        hotels = await client.hotel_avail(
            zone_code=zone_code,
            check_in=check_in,
            check_out=check_out,
            adults=adults,
            children=children,
            star_rating=star_rating,
            max_price=max_price,
            board_type=board_type,
            country_of_residence=country_of_residence,
        )
        from juniper_ai.app.juniper.serializers import hotels_to_llm_summary
        return hotels_to_llm_summary(hotels)
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
        logger.error("Unexpected error in search_hotels", exc_info=True)
        raise
