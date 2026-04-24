"""Hotel booking tool."""

import json
import logging
import uuid as uuid_mod
from datetime import datetime, timezone

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
from juniper_ai.app.agent.tools._user_context import get_current_user_id
from juniper_ai.app.juniper.mock_client import get_juniper_client

logger = logging.getLogger(__name__)


@tool
async def book_hotel(
    rate_plan_code: str,
    guest_name: str,
    guest_email: str,
    check_in: str,
    check_out: str,
    hotel_code: str = "",
    total_price: str = "",
    currency: str = "EUR",
    booking_code: str = "",
    booking_code_expires_at: str = "",
    country_of_residence: str = "ES",
    adults: int = 2,
    children: int = 0,
) -> str:
    """Book a hotel room. Only call this after the user has confirmed the booking.

    Args:
        rate_plan_code: The rate plan code for the selected room
        guest_name: Full name of the primary guest
        guest_email: Email address for booking confirmation
        check_in: Check-in date in YYYY-MM-DD format
        check_out: Check-out date in YYYY-MM-DD format
        hotel_code: JPCode of the hotel (from search_hotels / get_booking_rules).
            Juniper requires this on HotelBookingInfo/HotelCode and rejects the
            request with REQ_PRACTICE when missing.
        total_price: Total gross amount quoted by get_booking_rules. Used to
            build the PriceRange tolerance band that guards against silent
            upward price drift between valuation and booking.
        currency: ISO-4217 currency of ``total_price`` (EUR by default).
        booking_code: The BookingCode from get_booking_rules (required for
            real Juniper — mock flows tolerate absence).
        booking_code_expires_at: Expiration time of BookingCode in ISO format
        country_of_residence: Guest country of residence (ISO-3166-1 alpha-2, default ES)
        adults: Must match ``search_hotels`` / HotelAvail occupancy (default 2).
        children: Same — number of child guests (default 0).

    Returns:
        Booking confirmation with booking ID and details.
    """
    logger.info(
        "Tool book_hotel called: rate_plan_code=%s hotel_code=%s total=%s %s "
        "guest=%s check_in=%s check_out=%s country=%s",
        rate_plan_code, hotel_code, total_price, currency, guest_name,
        check_in, check_out, country_of_residence, adults, children,
    )
    date_error = validate_dates(check_in, check_out)
    if date_error:
        return date_error

    # Check if BookingCode has expired
    if booking_code_expires_at:
        try:
            expires = datetime.fromisoformat(booking_code_expires_at)
            if datetime.now(timezone.utc) > expires:
                return (
                    "The BookingCode has expired. Please call get_booking_rules again "
                    "with the same rate_plan_code to get a new BookingCode before booking."
                )
        except ValueError:
            pass  # Can't parse, proceed anyway

    user_id = get_current_user_id()

    # Generate ExternalBookingReference for timeout recovery
    external_ref = f"JA-{uuid_mod.uuid4().hex[:12].upper()}"

    # Split guest_name into name parts for Pax construction
    name_parts = guest_name.strip().split(maxsplit=1)
    first_name = name_parts[0] if name_parts else guest_name
    surname = name_parts[1] if len(name_parts) > 1 else ""

    client = get_juniper_client()
    try:
        result = await client.hotel_booking(
            rate_plan_code=rate_plan_code,
            guest_name=guest_name,
            guest_email=guest_email,
            check_in=check_in,
            check_out=check_out,
            hotel_code=hotel_code,
            total_price=total_price or None,
            currency=currency,
            user_id=user_id,
            booking_code=booking_code,
            country_of_residence=country_of_residence,
            external_booking_reference=external_ref,
            first_name=first_name,
            surname=surname,
            adults=adults,
            children=children,
        )

        booking_data = {
            "__booking__": True,
            "booking_id": result["booking_id"],
            "hotel_name": result["hotel_name"],
            "check_in": result["check_in"],
            "check_out": result["check_out"],
            "total_price": result["total_price"],
            "currency": result["currency"],
            "status": result["status"],
            "rate_plan_code": rate_plan_code,
            "guest_name": guest_name,
            "guest_email": guest_email,
            "country_of_residence": country_of_residence,
            "external_booking_reference": external_ref,
        }

        confirmation_text = (
            f"Booking Confirmed!\n"
            f"Booking ID: {result['booking_id']}\n"
            f"Hotel: {result['hotel_name']}\n"
            f"Check-in: {result['check_in']}\n"
            f"Check-out: {result['check_out']}\n"
            f"Total: {result['total_price']} {result['currency']}\n"
            f"Status: {result['status']}"
        )

        return f"{confirmation_text}\n\n__BOOKING_DATA__{json.dumps(booking_data)}__END_BOOKING_DATA__"
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
        logger.error("Unexpected error in book_hotel", exc_info=True)
        raise
