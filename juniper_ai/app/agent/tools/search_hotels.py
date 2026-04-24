"""Hotel search tool for LangGraph agent.

Static/SOAP cut-over (post Juniper ticket 1096690 ``REQ_PRACTICE`` fix):

- **PostgreSQL (L1)**:
    - Destination text → zone (``jpdcode`` + ``code`` + ``area_type``) via
      :func:`get_zone_code` / :func:`get_zone_candidates`.
    - Zone ``jpdcode`` (+ descendants) → JPCode list via
      :func:`list_hotels_in_zone_jpdcodes` (PostgreSQL recursive CTE).
- **Juniper SOAP**: availability and prices via
  ``hotel_avail(hotel_codes=...)`` only. ``DestinationZone`` is rejected by
  Juniper with ``REQ_PRACTICE`` for the ``TestXMLFlicknmix`` account and is
  no longer used by this tool.
"""

import logging
import time

from langchain_core.tools import tool

from juniper_ai.app.agent.tools._date_utils import validate_dates
from juniper_ai.app.config import settings
from juniper_ai.app.db.session import async_session
from juniper_ai.app.juniper.exceptions import (
    BookingPendingError,
    JuniperFaultError,
    NoResultsError,
    PriceChangedError,
    RoomUnavailableError,
    SOAPTimeoutError,
)
from juniper_ai.app.juniper.mock_client import get_juniper_client, mock_catalog_hotel_codes_upper
from juniper_ai.app.juniper.static_data import (
    get_zone_candidates,
    get_zone_code,
    list_hotels_in_zone_jpdcodes,
)

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
        "Tool search_hotels called with args: destination=%s, check_in=%s, check_out=%s, "
        "adults=%s, children=%s, star=%s, max_price=%s, board=%s",
        destination, check_in, check_out, adults, children, star_rating, max_price, board_type,
    )
    t_start = time.monotonic()
    date_error = validate_dates(check_in, check_out)
    if date_error:
        return date_error

    # Step 1: destination text → zone (jpdcode + code + area_type) via local cache.
    async with async_session() as db:
        zone = await get_zone_code(db, destination)

    if not zone:
        async with async_session() as db:
            candidates = await get_zone_candidates(db, destination, limit=5)
        if candidates:
            lines = [f"Could not find an exact match for '{destination}'. Did you mean:"]
            for c in candidates:
                lines.append(f"  - {c['name']} ({c['area_type']})")
            lines.append("Please reply with one of the names above so I can search.")
            return "\n".join(lines)
        return (
            f"Could not find any zone matching '{destination}'. "
            "Please check the destination name, or run static data sync "
            "(`python scripts/run_static_data_sync.py`) if the local catalogue is empty."
        )

    logger.info(
        "Resolved '%s' → jpdcode=%s code=%s (%s, %s)",
        destination, zone["jpdcode"], zone["code"], zone["name"], zone["area_type"],
    )

    # Step 2: zone.jpdcode (+ descendants) → JPCode list from local hotel_cache.
    # Juniper UAT requires HotelCodes for availability search; DestinationZone
    # is rejected with REQ_PRACTICE.
    max_candidates = settings.hotel_avail_max_candidates
    async with async_session() as db:
        jp_codes = await list_hotels_in_zone_jpdcodes(
            db,
            [zone["jpdcode"]],
            limit=max_candidates,
            expand_descendants=True,
            only_jpcodes=True,
        )

    if not jp_codes:
        return (
            f"No hotels are cached locally for {zone['name']} "
            f"({zone['area_type']}, jpdcode={zone['jpdcode']}). "
            "The static catalogue may need to be refreshed — please run "
            "`python scripts/run_static_data_sync.py` and retry."
        )

    if len(jp_codes) >= max_candidates:
        logger.info(
            "search_hotels: candidates capped at max_candidates=%d for zone %s "
            "(more hotels may exist in cache)",
            max_candidates, zone["jpdcode"],
        )

    # Step 3: Juniper SOAP HotelAvail with HotelCodes (client batches internally).
    client = get_juniper_client()
    try:
        hotels = await client.hotel_avail(
            hotel_codes=jp_codes,
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

        elapsed_ms = int((time.monotonic() - t_start) * 1000)
        if not hotels:
            logger.warning(
                "search_hotels ZERO_RESULTS: destination=%r zone.jpdcode=%s "
                "cached_jpcodes=%d star=%s max_price=%s board=%s juniper_use_mock=%s",
                destination, zone["jpdcode"], len(jp_codes),
                star_rating, max_price, board_type, settings.juniper_use_mock,
            )
            if settings.juniper_use_mock:
                mock_codes = mock_catalog_hotel_codes_upper()
                overlap = [c for c in jp_codes if str(c).strip().upper() in mock_codes]
                listed = ", ".join(sorted(mock_codes))
                if not overlap:
                    return (
                        "[Mock Juniper] Your local hotel cache returned "
                        f"{len(jp_codes)} JP code(s) for **{zone['name']}**, but **none** of them are in the "
                        "mock supplier catalogue, so availability is empty — this is **not** a network outage "
                        "or SOAP failure. "
                        f"Mock hotel codes are: {listed}. "
                        "For Palma offline tests, run static data sync so **JP046300** is present in "
                        "`hotel_cache` for this zone. "
                        "Also avoid filters that exclude the mock row (Palma mock is **Room Only**, ~291 EUR)."
                    )
                return (
                    "[Mock Juniper] Some cached JP codes match the mock catalogue "
                    f"({', '.join(overlap[:5])}{'…' if len(overlap) > 5 else ''}), but **all** rows were "
                    "removed by your search filters "
                    f"(star_rating={star_rating}, max_price={max_price}, board_type={board_type!r}). "
                    "Retry without board/star/price filters, or use **Room Only** for JP046300."
                )
            return (
                f"No hotels found in {zone['name']} for {check_in} to {check_out} "
                "(the supplier returned no bookable options for the cached hotel codes in this zone). "
                "Try different dates, a nearby area, or relax filters."
            )

        logger.info(
            "search_hotels OK: destination=%r zone.jpdcode=%s jpcodes=%d "
            "dates=%s..%s results=%d elapsed=%dms",
            destination, zone["jpdcode"], len(jp_codes),
            check_in, check_out, len(hotels), elapsed_ms,
        )
        return hotels_to_llm_summary(hotels)
    except SOAPTimeoutError:
        elapsed_ms = int((time.monotonic() - t_start) * 1000)
        logger.warning(
            "search_hotels TIMEOUT: destination=%r zone.jpdcode=%s "
            "jpcodes=%d elapsed=%dms",
            destination, zone["jpdcode"], len(jp_codes), elapsed_ms,
        )
        return "Hotel booking service is temporarily unavailable. Please try again in a moment."
    except RoomUnavailableError:
        return "This room is no longer available. Let me search for alternatives."
    except PriceChangedError as e:
        return (
            f"The price has changed from {e.old_price} to {e.new_price}. "
            "Would you like to proceed with the new price?"
        )
    except NoResultsError:
        elapsed_ms = int((time.monotonic() - t_start) * 1000)
        logger.info(
            "search_hotels EMPTY: destination=%r zone.jpdcode=%s "
            "jpcodes=%d dates=%s..%s elapsed=%dms",
            destination, zone["jpdcode"], len(jp_codes),
            check_in, check_out, elapsed_ms,
        )
        return (
            f"No hotels found in {zone['name']} for {check_in} to {check_out}. "
            "Try different dates or a nearby area."
        )
    except JuniperFaultError as e:
        elapsed_ms = int((time.monotonic() - t_start) * 1000)
        # Client already emitted one aggregated fault log with fault_code +
        # batch index; re-log here with search context so operators can
        # correlate the user-facing failure with the SOAP trace.
        logger.error(
            "search_hotels FAULT: destination=%r zone.jpdcode=%s "
            "jpcodes=%d fault_code=%s elapsed=%dms",
            destination, zone["jpdcode"], len(jp_codes), e.fault_code, elapsed_ms,
        )
        return f"The booking system returned an error: {e}"
    except BookingPendingError:
        return "Your booking is being processed. Please wait a moment."
    except Exception:
        logger.error("Unexpected error in search_hotels", exc_info=True)
        raise
