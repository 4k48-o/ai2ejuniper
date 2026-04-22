"""Tests for agent tool error handling (search_hotels, book_hotel)."""

import json
import re
import uuid
from datetime import date, timedelta

import pytest
from unittest.mock import AsyncMock, patch, MagicMock

from juniper_ai.app.db.models import BookingStatus
from juniper_ai.app.juniper.exceptions import (
    SOAPTimeoutError,
    RoomUnavailableError,
    NoResultsError,
    JuniperFaultError,
    PriceChangedError,
    BookingPendingError,
)

_CI = (date.today() + timedelta(days=30)).isoformat()
_CO = (date.today() + timedelta(days=33)).isoformat()


# ---------------------------------------------------------------------------
# search_hotels tests
# ---------------------------------------------------------------------------


_MOCK_ZONE = {"jpdcode": "JPD086855", "code": "49435", "name": "Barcelona", "area_type": "CTY"}
# search_hotels calls list_hotels_in_zone_jpdcodes(only_jpcodes=True), which
# returns list[str]. Patches below should match that shape.
_MOCK_CACHE = ["JP046300", "JP046301"]


@pytest.mark.asyncio
async def test_search_hotels_happy_path():
    mock_client = AsyncMock()
    mock_client.hotel_avail.return_value = [
        {
            "hotel_code": "H1",
            "name": "Test Hotel",
            "category": "4 stars",
            "address": "123 Test St",
            "city": "Barcelona",
            "rate_plan_code": "RPC_001",
            "total_price": "150.00",
            "currency": "EUR",
            "board_type": "Bed & Breakfast",
            "room_type": "Double",
            "cancellation_policy": "Free cancellation",
        }
    ]

    with patch("juniper_ai.app.agent.tools.search_hotels.get_juniper_client", return_value=mock_client), \
         patch("juniper_ai.app.agent.tools.search_hotels.get_zone_code", return_value=_MOCK_ZONE), \
         patch("juniper_ai.app.agent.tools.search_hotels.list_hotels_in_zone_jpdcodes", return_value=_MOCK_CACHE):
        from juniper_ai.app.agent.tools.search_hotels import search_hotels

        result = await search_hotels.ainvoke({
            "destination": "Barcelona",
            "check_in": _CI,
            "check_out": _CO,
        })

    assert "Test Hotel" in result
    assert "150.00" in result
    # Must use HotelCodes (JPCodes from local cache), not DestinationZone.
    kw = mock_client.hotel_avail.await_args.kwargs
    assert kw["hotel_codes"] == ["JP046300", "JP046301"]
    assert "zone_code" not in kw


# §8: 3-city parametric coverage (happy-path + empty-inventory per city).
_CITY_CASES = [
    pytest.param(
        {"jpdcode": "JPD054557", "code": "15011", "name": "Palma de Mallorca", "area_type": "CTY"},
        ["JP046300"],
        id="palma-available",
    ),
    pytest.param(
        {"jpdcode": "JPD013826", "code": "13826", "name": "Dubai City", "area_type": "CTY"},
        ["JP099001", "JP099002"],
        id="dubai-available",
    ),
    pytest.param(
        {"jpdcode": "JPD086855", "code": "49435", "name": "Barcelona", "area_type": "CTY"},
        ["JP046400", "JP046401", "JP046402"],
        id="barcelona-available",
    ),
]


@pytest.mark.asyncio
@pytest.mark.parametrize("zone,jpcodes", _CITY_CASES)
async def test_search_hotels_multi_city_happy(zone, jpcodes):
    """Happy path across 3 supplier-documented cities, asserting HotelCodes plumbing."""
    mock_client = AsyncMock()
    mock_client.hotel_avail.return_value = [
        {"name": f"Hotel-{c}", "total_price": "100.00", "currency": "EUR",
         "rate_plan_code": f"RPC_{c}", "category": "4 stars", "address": "",
         "city": zone["name"], "board_type": "Bed & Breakfast",
         "room_type": "Double", "cancellation_policy": ""}
        for c in jpcodes
    ]

    with patch("juniper_ai.app.agent.tools.search_hotels.get_juniper_client", return_value=mock_client), \
         patch("juniper_ai.app.agent.tools.search_hotels.get_zone_code", return_value=zone), \
         patch("juniper_ai.app.agent.tools.search_hotels.list_hotels_in_zone_jpdcodes", return_value=jpcodes):
        from juniper_ai.app.agent.tools.search_hotels import search_hotels

        result = await search_hotels.ainvoke({
            "destination": zone["name"],
            "check_in": _CI,
            "check_out": _CO,
        })

    # First hotel name should appear in LLM-facing summary.
    assert f"Hotel-{jpcodes[0]}" in result
    kw = mock_client.hotel_avail.await_args.kwargs
    assert kw["hotel_codes"] == jpcodes
    assert "zone_code" not in kw


@pytest.mark.asyncio
@pytest.mark.parametrize("zone", [c.values[0] for c in _CITY_CASES])
async def test_search_hotels_multi_city_no_inventory(zone):
    """Inventory-empty path: each city surfaces a 'no hotels' message with its name."""
    mock_client = AsyncMock()
    mock_client.hotel_avail.side_effect = NoResultsError()

    with patch("juniper_ai.app.agent.tools.search_hotels.get_juniper_client", return_value=mock_client), \
         patch("juniper_ai.app.agent.tools.search_hotels.get_zone_code", return_value=zone), \
         patch("juniper_ai.app.agent.tools.search_hotels.list_hotels_in_zone_jpdcodes", return_value=["JP0XXX"]):
        from juniper_ai.app.agent.tools.search_hotels import search_hotels

        result = await search_hotels.ainvoke({
            "destination": zone["name"],
            "check_in": _CI,
            "check_out": _CO,
        })

    assert "no hotels found" in result.lower()
    assert zone["name"] in result


@pytest.mark.asyncio
async def test_search_hotels_soap_timeout():
    mock_client = AsyncMock()
    mock_client.hotel_avail.side_effect = SOAPTimeoutError()

    with patch("juniper_ai.app.agent.tools.search_hotels.get_juniper_client", return_value=mock_client), \
         patch("juniper_ai.app.agent.tools.search_hotels.get_zone_code", return_value=_MOCK_ZONE), \
         patch("juniper_ai.app.agent.tools.search_hotels.list_hotels_in_zone_jpdcodes", return_value=_MOCK_CACHE):
        from juniper_ai.app.agent.tools.search_hotels import search_hotels

        result = await search_hotels.ainvoke({
            "destination": "Barcelona",
            "check_in": _CI,
            "check_out": _CO,
        })

    assert "temporarily unavailable" in result.lower()


@pytest.mark.asyncio
async def test_search_hotels_room_unavailable():
    mock_client = AsyncMock()
    mock_client.hotel_avail.side_effect = RoomUnavailableError()

    with patch("juniper_ai.app.agent.tools.search_hotels.get_juniper_client", return_value=mock_client), \
         patch("juniper_ai.app.agent.tools.search_hotels.get_zone_code", return_value=_MOCK_ZONE), \
         patch("juniper_ai.app.agent.tools.search_hotels.list_hotels_in_zone_jpdcodes", return_value=_MOCK_CACHE):
        from juniper_ai.app.agent.tools.search_hotels import search_hotels

        result = await search_hotels.ainvoke({
            "destination": "Barcelona",
            "check_in": _CI,
            "check_out": _CO,
        })

    assert "no longer available" in result.lower()


@pytest.mark.asyncio
async def test_search_hotels_unexpected_exception_reraises():
    mock_client = AsyncMock()
    mock_client.hotel_avail.side_effect = RuntimeError("unexpected")

    with patch("juniper_ai.app.agent.tools.search_hotels.get_juniper_client", return_value=mock_client), \
         patch("juniper_ai.app.agent.tools.search_hotels.get_zone_code", return_value=_MOCK_ZONE), \
         patch("juniper_ai.app.agent.tools.search_hotels.list_hotels_in_zone_jpdcodes", return_value=_MOCK_CACHE):
        from juniper_ai.app.agent.tools.search_hotels import search_hotels

        with pytest.raises(RuntimeError, match="unexpected"):
            await search_hotels.ainvoke({
                "destination": "Barcelona",
                "check_in": _CI,
                "check_out": _CO,
            })


@pytest.mark.asyncio
async def test_search_hotels_no_results():
    mock_client = AsyncMock()
    mock_client.hotel_avail.side_effect = NoResultsError()

    with patch("juniper_ai.app.agent.tools.search_hotels.get_juniper_client", return_value=mock_client), \
         patch("juniper_ai.app.agent.tools.search_hotels.get_zone_code", return_value=_MOCK_ZONE), \
         patch("juniper_ai.app.agent.tools.search_hotels.list_hotels_in_zone_jpdcodes", return_value=_MOCK_CACHE):
        from juniper_ai.app.agent.tools.search_hotels import search_hotels

        result = await search_hotels.ainvoke({
            "destination": "NowhereVille",
            "check_in": _CI,
            "check_out": _CO,
        })

    assert "no hotels found" in result.lower()


@pytest.mark.asyncio
async def test_search_hotels_empty_local_cache_prompts_sync():
    """Zone resolved but local hotel_cache has no JPCodes → user gets a sync hint."""
    empty_cache: list[str] = []
    mock_client = AsyncMock()

    with patch("juniper_ai.app.agent.tools.search_hotels.get_juniper_client", return_value=mock_client), \
         patch("juniper_ai.app.agent.tools.search_hotels.get_zone_code", return_value=_MOCK_ZONE), \
         patch("juniper_ai.app.agent.tools.search_hotels.list_hotels_in_zone_jpdcodes", return_value=empty_cache):
        from juniper_ai.app.agent.tools.search_hotels import search_hotels

        result = await search_hotels.ainvoke({
            "destination": "Barcelona",
            "check_in": _CI,
            "check_out": _CO,
        })

    assert "cached locally" in result.lower()
    assert "run_static_data_sync" in result
    # SOAP must NOT be called when we have no JPCodes.
    mock_client.hotel_avail.assert_not_awaited()


# ---------------------------------------------------------------------------
# check_availability tests (TOOL-06 ~ TOOL-08)
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_check_availability_valid_rate_plan_returns_price():
    mock_client = AsyncMock()
    mock_client.hotel_check_avail.return_value = {
        "available": True,
        "total_price": "180.00",
        "currency": "EUR",
        "rate_plan_code": "RPC_001_DBL_BB",
    }

    with patch("juniper_ai.app.agent.tools.check_availability.get_juniper_client", return_value=mock_client):
        from juniper_ai.app.agent.tools.check_availability import check_availability

        result = await check_availability.ainvoke({"rate_plan_code": "RPC_001_DBL_BB"})

    assert "Available: True" in result
    assert "180.00" in result
    assert "EUR" in result
    assert "RPC_001_DBL_BB" in result


@pytest.mark.asyncio
async def test_check_availability_invalid_code_room_unavailable_message():
    mock_client = AsyncMock()
    mock_client.hotel_check_avail.side_effect = RoomUnavailableError("bad code")

    with patch("juniper_ai.app.agent.tools.check_availability.get_juniper_client", return_value=mock_client):
        from juniper_ai.app.agent.tools.check_availability import check_availability

        result = await check_availability.ainvoke({"rate_plan_code": "INVALID_RPC"})

    assert "no longer available" in result.lower()


@pytest.mark.asyncio
async def test_check_availability_soap_timeout():
    mock_client = AsyncMock()
    mock_client.hotel_check_avail.side_effect = SOAPTimeoutError()

    with patch("juniper_ai.app.agent.tools.check_availability.get_juniper_client", return_value=mock_client):
        from juniper_ai.app.agent.tools.check_availability import check_availability

        result = await check_availability.ainvoke({"rate_plan_code": "RPC_001_DBL_BB"})

    assert "temporarily unavailable" in result.lower()


# ---------------------------------------------------------------------------
# get_booking_rules tests (TOOL-09 ~ TOOL-10)
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_get_booking_rules_valid_rate_plan_returns_policy_and_price():
    mock_client = AsyncMock()
    mock_client.hotel_booking_rules.return_value = {
        "valid": True,
        "rate_plan_code": "RPC_001_DBL_BB",
        "total_price": "180.00",
        "currency": "EUR",
        "cancellation_policy": "Free cancellation until 48h before check-in",
        "remarks": "",
    }

    with patch("juniper_ai.app.agent.tools.booking_rules.get_juniper_client", return_value=mock_client):
        from juniper_ai.app.agent.tools.booking_rules import get_booking_rules

        result = await get_booking_rules.ainvoke({"rate_plan_code": "RPC_001_DBL_BB"})

    assert "Valid: True" in result
    assert "180.00" in result
    assert "EUR" in result
    assert "Free cancellation until 48h" in result


@pytest.mark.asyncio
async def test_get_booking_rules_invalid_code_room_unavailable_message():
    mock_client = AsyncMock()
    mock_client.hotel_booking_rules.side_effect = RoomUnavailableError("unknown rpc")

    with patch("juniper_ai.app.agent.tools.booking_rules.get_juniper_client", return_value=mock_client):
        from juniper_ai.app.agent.tools.booking_rules import get_booking_rules

        result = await get_booking_rules.ainvoke({"rate_plan_code": "BAD_RPC"})

    assert "no longer available" in result.lower()


# ---------------------------------------------------------------------------
# book_hotel tests
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_book_hotel_happy_path():
    mock_client = AsyncMock()
    mock_client.hotel_booking.return_value = {
        "booking_id": "BK-12345",
        "hotel_name": "Test Hotel",
        "check_in": _CI,
        "check_out": _CO,
        "total_price": "540.00",
        "currency": "EUR",
        "status": "confirmed",
    }

    with patch("juniper_ai.app.agent.tools.book_hotel.get_juniper_client", return_value=mock_client), \
         patch("juniper_ai.app.agent.tools.book_hotel.get_current_user_id", return_value="user-test"):
        from juniper_ai.app.agent.tools.book_hotel import book_hotel

        result = await book_hotel.ainvoke({
            "rate_plan_code": "RPC_001",
            "guest_name": "John Doe",
            "guest_email": "john@example.com",
            "check_in": _CI,
            "check_out": _CO,
        })

    assert "BK-12345" in result
    assert "confirmed" in result.lower()
    assert "__BOOKING_DATA__" in result
    assert "__END_BOOKING_DATA__" in result


@pytest.mark.asyncio
async def test_book_hotel_passes_check_in_and_check_out_to_client():
    """TOOL-13: check_in / check_out kwargs match tool input (and user_id forwarded)."""
    mock_client = AsyncMock()
    mock_client.hotel_booking.return_value = {
        "booking_id": "BK-12345",
        "hotel_name": "Test Hotel",
        "check_in": "2026-06-01",
        "check_out": "2026-06-10",
        "total_price": "540.00",
        "currency": "EUR",
        "status": "confirmed",
    }

    with patch("juniper_ai.app.agent.tools.book_hotel.get_juniper_client", return_value=mock_client), \
         patch("juniper_ai.app.agent.tools.book_hotel.get_current_user_id", return_value="user-ctx-1"):
        from juniper_ai.app.agent.tools.book_hotel import book_hotel

        await book_hotel.ainvoke({
            "rate_plan_code": "RPC_001",
            "guest_name": "John Doe",
            "guest_email": "john@example.com",
            "check_in": "2026-06-01",
            "check_out": "2026-06-10",
        })

    mock_client.hotel_booking.assert_awaited_once()
    kw = mock_client.hotel_booking.await_args.kwargs
    assert kw["check_in"] == "2026-06-01"
    assert kw["check_out"] == "2026-06-10"
    assert kw["rate_plan_code"] == "RPC_001"
    assert kw["guest_name"] == "John Doe"
    assert kw["guest_email"] == "john@example.com"
    assert kw["user_id"] == "user-ctx-1"


@pytest.mark.asyncio
async def test_book_hotel_soap_timeout():
    mock_client = AsyncMock()
    mock_client.hotel_booking.side_effect = SOAPTimeoutError()

    with patch("juniper_ai.app.agent.tools.book_hotel.get_juniper_client", return_value=mock_client), \
         patch("juniper_ai.app.agent.tools.book_hotel.get_current_user_id", return_value="user-test"):
        from juniper_ai.app.agent.tools.book_hotel import book_hotel

        result = await book_hotel.ainvoke({
            "rate_plan_code": "RPC_001",
            "guest_name": "John Doe",
            "guest_email": "john@example.com",
            "check_in": _CI,
            "check_out": _CO,
        })

    assert "temporarily unavailable" in result.lower()


@pytest.mark.asyncio
async def test_book_hotel_room_unavailable():
    mock_client = AsyncMock()
    mock_client.hotel_booking.side_effect = RoomUnavailableError()

    with patch("juniper_ai.app.agent.tools.book_hotel.get_juniper_client", return_value=mock_client), \
         patch("juniper_ai.app.agent.tools.book_hotel.get_current_user_id", return_value="user-test"):
        from juniper_ai.app.agent.tools.book_hotel import book_hotel

        result = await book_hotel.ainvoke({
            "rate_plan_code": "RPC_INVALID",
            "guest_name": "John Doe",
            "guest_email": "john@example.com",
            "check_in": _CI,
            "check_out": _CO,
        })

    assert "no longer available" in result.lower()


@pytest.mark.asyncio
async def test_book_hotel_unexpected_exception_reraises():
    mock_client = AsyncMock()
    mock_client.hotel_booking.side_effect = ValueError("unexpected booking error")

    with patch("juniper_ai.app.agent.tools.book_hotel.get_juniper_client", return_value=mock_client), \
         patch("juniper_ai.app.agent.tools.book_hotel.get_current_user_id", return_value="user-test"):
        from juniper_ai.app.agent.tools.book_hotel import book_hotel

        with pytest.raises(ValueError, match="unexpected booking error"):
            await book_hotel.ainvoke({
                "rate_plan_code": "RPC_001",
                "guest_name": "John Doe",
                "guest_email": "john@example.com",
                "check_in": _CI,
                "check_out": _CO,
            })


@pytest.mark.asyncio
async def test_book_hotel_price_changed():
    mock_client = AsyncMock()
    mock_client.hotel_booking.side_effect = PriceChangedError("100.00", "120.00", "EUR")

    with patch("juniper_ai.app.agent.tools.book_hotel.get_juniper_client", return_value=mock_client), \
         patch("juniper_ai.app.agent.tools.book_hotel.get_current_user_id", return_value="user-test"):
        from juniper_ai.app.agent.tools.book_hotel import book_hotel

        result = await book_hotel.ainvoke({
            "rate_plan_code": "RPC_001",
            "guest_name": "John Doe",
            "guest_email": "john@example.com",
            "check_in": _CI,
            "check_out": _CO,
        })

    assert "price has changed" in result.lower()
    assert "100.00" in result
    assert "120.00" in result


@pytest.mark.asyncio
async def test_book_hotel_booking_pending():
    """TOOL-17: BookingPendingError → user-facing pending message."""
    mock_client = AsyncMock()
    mock_client.hotel_booking.side_effect = BookingPendingError("idem-key-1")

    with patch("juniper_ai.app.agent.tools.book_hotel.get_juniper_client", return_value=mock_client), \
         patch("juniper_ai.app.agent.tools.book_hotel.get_current_user_id", return_value="user-test"):
        from juniper_ai.app.agent.tools.book_hotel import book_hotel

        result = await book_hotel.ainvoke({
            "rate_plan_code": "RPC_001",
            "guest_name": "John Doe",
            "guest_email": "john@example.com",
            "check_in": _CI,
            "check_out": _CO,
        })

    assert "being processed" in result.lower()
    assert "wait a moment" in result.lower()


class _FakeAsyncSessionCM:
    """Minimal async context manager for patching `async_session()`."""

    def __init__(self, db):
        self._db = db

    async def __aenter__(self):
        return self._db

    async def __aexit__(self, exc_type, exc, tb):
        return False


# ---------------------------------------------------------------------------
# read_booking tests (TOOL-19 ~ TOOL-21) — local DB, no supplier SOAP
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_read_booking_returns_details_when_found():
    """TOOL-19: row scoped by user + juniper_booking_id → formatted details."""
    user_uuid = uuid.uuid4()
    booking = MagicMock()
    booking.juniper_booking_id = "JNP-READTEST"
    booking.status = BookingStatus.confirmed
    booking.hotel_name = "Sea View Inn"
    booking.check_in = "2026-08-01"
    booking.check_out = "2026-08-05"
    booking.total_price = "410.00"
    booking.currency = "EUR"
    booking.booking_details = {"guest_name": "River Chen", "guest_email": "river@example.org"}

    mock_db = AsyncMock()
    row_result = MagicMock()
    row_result.scalar_one_or_none.return_value = booking
    mock_db.execute = AsyncMock(return_value=row_result)

    with patch("juniper_ai.app.agent.tools.read_booking.get_current_user_uuid", return_value=user_uuid), \
         patch(
             "juniper_ai.app.agent.tools.read_booking.async_session",
             return_value=_FakeAsyncSessionCM(mock_db),
         ):
        from juniper_ai.app.agent.tools.read_booking import read_booking

        result = await read_booking.ainvoke({"booking_id": "JNP-READTEST"})

    assert "JNP-READTEST" in result
    assert "confirmed" in result.lower()
    assert "Sea View Inn" in result
    assert "2026-08-01" in result
    assert "410.00" in result
    assert "EUR" in result
    assert "River Chen" in result
    assert "river@example.org" in result


@pytest.mark.asyncio
async def test_read_booking_not_found_returns_local_message():
    """TOOL-20: no row → fixed copy (not supplier not_found)."""
    mock_db = AsyncMock()
    row_result = MagicMock()
    row_result.scalar_one_or_none.return_value = None
    mock_db.execute = AsyncMock(return_value=row_result)

    with patch("juniper_ai.app.agent.tools.read_booking.get_current_user_uuid", return_value=uuid.uuid4()), \
         patch(
             "juniper_ai.app.agent.tools.read_booking.async_session",
             return_value=_FakeAsyncSessionCM(mock_db),
         ):
        from juniper_ai.app.agent.tools.read_booking import read_booking

        result = await read_booking.ainvoke({"booking_id": "JNP-NOSUCH"})

    assert result == "Booking not found or it does not belong to you."


@pytest.mark.asyncio
async def test_read_booking_db_error_propagates():
    """TOOL-21: no SOAP path; DB failures are not swallowed."""
    mock_db = AsyncMock()
    mock_db.execute = AsyncMock(side_effect=RuntimeError("db connection failed"))

    with patch("juniper_ai.app.agent.tools.read_booking.get_current_user_uuid", return_value=uuid.uuid4()), \
         patch(
             "juniper_ai.app.agent.tools.read_booking.async_session",
             return_value=_FakeAsyncSessionCM(mock_db),
         ):
        from juniper_ai.app.agent.tools.read_booking import read_booking

        with pytest.raises(RuntimeError, match="db connection failed"):
            await read_booking.ainvoke({"booking_id": "JNP-ANY"})


# ---------------------------------------------------------------------------
# list_bookings tests (TOOL-22 ~ TOOL-25) — local DB only
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_list_bookings_formats_multiple_rows():
    """TOOL-22: non-empty list → header + per-booking lines."""
    user_uuid = uuid.uuid4()
    b1 = MagicMock()
    b1.juniper_booking_id = "JNP-AAA11111"
    b1.hotel_name = "Hotel Alpha"
    b1.check_in = "2026-09-01"
    b1.check_out = "2026-09-03"
    b1.total_price = "200.00"
    b1.currency = "EUR"
    b1.status = BookingStatus.confirmed
    b1.booking_details = {"guest_name": "Pat Lee", "guest_email": "pat@example.com"}

    b2 = MagicMock()
    b2.juniper_booking_id = "JNP-BBB22222"
    b2.hotel_name = "Hotel Beta"
    b2.check_in = "2026-10-01"
    b2.check_out = "2026-10-05"
    b2.total_price = "350.00"
    b2.currency = "USD"
    b2.status = BookingStatus.cancelled
    b2.booking_details = None

    mock_db = AsyncMock()
    list_result = MagicMock()
    list_result.scalars.return_value.all.return_value = [b1, b2]
    mock_db.execute = AsyncMock(return_value=list_result)

    with patch("juniper_ai.app.agent.tools.list_bookings.get_current_user_uuid", return_value=user_uuid), \
         patch(
             "juniper_ai.app.agent.tools.list_bookings.async_session",
             return_value=_FakeAsyncSessionCM(mock_db),
         ):
        from juniper_ai.app.agent.tools.list_bookings import list_bookings

        result = await list_bookings.ainvoke({})

    assert "Found 2 booking(s)" in result
    assert "JNP-AAA11111" in result
    assert "Hotel Alpha" in result
    assert "JNP-BBB22222" in result
    assert "cancelled" in result.lower()
    assert "Pat Lee" in result
    assert "pat@example.com" in result
    assert "Guest:" in result
    assert "Email:" in result


@pytest.mark.asyncio
async def test_list_bookings_empty_returns_message():
    """TOOL-23: zero rows → fixed empty copy."""
    mock_db = AsyncMock()
    list_result = MagicMock()
    list_result.scalars.return_value.all.return_value = []
    mock_db.execute = AsyncMock(return_value=list_result)

    with patch("juniper_ai.app.agent.tools.list_bookings.get_current_user_uuid", return_value=uuid.uuid4()), \
         patch(
             "juniper_ai.app.agent.tools.list_bookings.async_session",
             return_value=_FakeAsyncSessionCM(mock_db),
         ):
        from juniper_ai.app.agent.tools.list_bookings import list_bookings

        result = await list_bookings.ainvoke({})

    assert result == "No bookings found. The user has no booking history."


@pytest.mark.asyncio
async def test_list_bookings_uses_local_db_query_not_supplier():
    """TOOL-24: SELECT Booking by user_id + ORDER BY created_at DESC (no Juniper client)."""
    mock_db = AsyncMock()
    list_result = MagicMock()
    list_result.scalars.return_value.all.return_value = []
    mock_db.execute = AsyncMock(return_value=list_result)

    with patch("juniper_ai.app.agent.tools.list_bookings.get_current_user_uuid", return_value=uuid.uuid4()), \
         patch(
             "juniper_ai.app.agent.tools.list_bookings.async_session",
             return_value=_FakeAsyncSessionCM(mock_db),
         ):
        from juniper_ai.app.agent.tools.list_bookings import list_bookings

        await list_bookings.ainvoke({})

    mock_db.execute.assert_awaited_once()
    stmt = mock_db.execute.await_args.args[0]
    sql = str(stmt)
    assert "bookings.user_id" in sql
    assert "ORDER BY bookings.created_at DESC" in sql


@pytest.mark.asyncio
async def test_list_bookings_db_error_propagates():
    """TOOL-25: DB failure not swallowed (no SOAP in tool)."""
    mock_db = AsyncMock()
    mock_db.execute = AsyncMock(side_effect=OSError("disk full"))

    with patch("juniper_ai.app.agent.tools.list_bookings.get_current_user_uuid", return_value=uuid.uuid4()), \
         patch(
             "juniper_ai.app.agent.tools.list_bookings.async_session",
             return_value=_FakeAsyncSessionCM(mock_db),
         ):
        from juniper_ai.app.agent.tools.list_bookings import list_bookings

        with pytest.raises(OSError, match="disk full"):
            await list_bookings.ainvoke({})


@pytest.mark.asyncio
async def test_cancel_booking_embeds_booking_event():
    mock_client = AsyncMock()
    mock_client.cancel_booking.return_value = {"booking_id": "JNP-ABC12345", "status": "cancelled"}

    with patch("juniper_ai.app.agent.tools.cancel_booking.get_juniper_client", return_value=mock_client), \
         patch("juniper_ai.app.agent.tools.cancel_booking.get_current_user_id", return_value="user-1"):
        from juniper_ai.app.agent.tools.cancel_booking import cancel_booking

        result = await cancel_booking.ainvoke({"booking_id": "JNP-ABC12345"})

    assert "__BOOKING_EVENT__" in result
    assert "__END_BOOKING_EVENT__" in result
    assert "booking.cancelled" in result


@pytest.mark.asyncio
async def test_cancel_booking_unknown_id_mock_still_cancelled():
    """TOOL-27: MockJuniperClient returns cancelled for IDs not in MOCK_BOOKINGS."""
    from juniper_ai.app.juniper.mock_client import MockJuniperClient

    booking_id = f"JNP-{uuid.uuid4().hex[:8].upper()}"
    client = MockJuniperClient()

    with patch("juniper_ai.app.agent.tools.cancel_booking.get_juniper_client", return_value=client), \
         patch("juniper_ai.app.agent.tools.cancel_booking.get_current_user_id", return_value="user-1"):
        from juniper_ai.app.agent.tools.cancel_booking import cancel_booking

        result = await cancel_booking.ainvoke({"booking_id": booking_id})

    assert "cancelled" in result.lower()
    assert booking_id in result
    assert "__BOOKING_EVENT__" in result
    assert "booking.cancelled" in result


@pytest.mark.asyncio
async def test_cancel_booking_soap_timeout():
    """TOOL-28: SOAPTimeoutError → user-facing unavailable message."""
    mock_client = AsyncMock()
    mock_client.cancel_booking.side_effect = SOAPTimeoutError()

    with patch("juniper_ai.app.agent.tools.cancel_booking.get_juniper_client", return_value=mock_client), \
         patch("juniper_ai.app.agent.tools.cancel_booking.get_current_user_id", return_value="user-1"):
        from juniper_ai.app.agent.tools.cancel_booking import cancel_booking

        result = await cancel_booking.ainvoke({"booking_id": "JNP-ANY12345"})

    assert "temporarily unavailable" in result.lower()


@pytest.mark.asyncio
async def test_modify_booking_returns_preview():
    mock_client = AsyncMock()
    mock_client.hotel_modify = AsyncMock(
        return_value={
            "booking_id": "JNP-XYZ98765",
            "status": "modification_pending",
            "check_in": "2026-05-01",
            "check_out": "2026-05-03",
            "modify_code": "MC-TEST1234",
        },
    )

    with patch("juniper_ai.app.agent.tools.modify_booking.get_juniper_client", return_value=mock_client), \
         patch("juniper_ai.app.agent.tools.modify_booking.get_current_user_id", return_value="user-1"):
        from juniper_ai.app.agent.tools.modify_booking import modify_booking

        result = await modify_booking.ainvoke(
            {"booking_id": "JNP-XYZ98765", "new_check_in": "2026-05-01", "new_check_out": "2026-05-03"}
        )

    assert "Modification Preview" in result
    assert "MC-TEST1234" in result
    mock_client.hotel_modify.assert_awaited_once()


@pytest.mark.asyncio
async def test_modify_booking_unknown_id_returns_not_found():
    """TOOL-30: MockJuniperClient returns status=not_found for unknown booking_id."""
    from juniper_ai.app.juniper.mock_client import MockJuniperClient

    booking_id = f"JNP-{uuid.uuid4().hex[:8].upper()}"
    client = MockJuniperClient()

    with patch("juniper_ai.app.agent.tools.modify_booking.get_juniper_client", return_value=client), \
         patch("juniper_ai.app.agent.tools.modify_booking.get_current_user_id", return_value="user-1"):
        from juniper_ai.app.agent.tools.modify_booking import modify_booking

        result = await modify_booking.ainvoke(
            {"booking_id": booking_id, "new_check_in": "2026-06-01", "new_check_out": "2026-06-05"}
        )

    assert "not_found" in result.lower()
    assert booking_id in result


@pytest.mark.asyncio
async def test_modify_booking_check_in_only_preserves_check_out():
    """TOOL-31: only new_check_in is forwarded; check_out stays from existing booking."""
    from juniper_ai.app.juniper.mock_client import MockJuniperClient

    client = MockJuniperClient()
    book = await client.hotel_booking(
        "RPC_001_DBL_BB",
        guest_name="Pat",
        guest_email="pat@example.com",
    )
    bid = book["booking_id"]
    orig_out = book["check_out"]

    with patch("juniper_ai.app.agent.tools.modify_booking.get_juniper_client", return_value=client), \
         patch("juniper_ai.app.agent.tools.modify_booking.get_current_user_id", return_value="user-1"):
        from juniper_ai.app.agent.tools.modify_booking import modify_booking

        result = await modify_booking.ainvoke(
            {"booking_id": bid, "new_check_in": "2026-12-01"}
        )

    assert "2026-12-01" in result
    assert orig_out in result
    assert "Modification Preview" in result
    assert "ModifyCode" in result


@pytest.mark.asyncio
async def test_modify_booking_soap_timeout():
    """TOOL-32: SOAPTimeoutError → temporarily unavailable message."""
    mock_client = AsyncMock()
    mock_client.hotel_modify = AsyncMock(side_effect=SOAPTimeoutError())

    with patch("juniper_ai.app.agent.tools.modify_booking.get_juniper_client", return_value=mock_client), \
         patch("juniper_ai.app.agent.tools.modify_booking.get_current_user_id", return_value="user-1"):
        from juniper_ai.app.agent.tools.modify_booking import modify_booking

        result = await modify_booking.ainvoke(
            {"booking_id": "JNP-ANY", "new_check_in": "2026-05-01", "new_check_out": "2026-05-03"}
        )

    assert "temporarily unavailable" in result.lower()


# ---------------------------------------------------------------------------
# User context missing / None — guard tests
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_list_bookings_no_user_context_returns_error():
    """get_current_user_uuid returns None → friendly error, no DB query."""
    with patch("juniper_ai.app.agent.tools.list_bookings.get_current_user_uuid", return_value=None):
        from juniper_ai.app.agent.tools.list_bookings import list_bookings

        result = await list_bookings.ainvoke({})

    assert "unable to identify" in result.lower()


@pytest.mark.asyncio
async def test_read_booking_no_user_context_returns_error():
    """get_current_user_uuid returns None → friendly error, no DB query."""
    with patch("juniper_ai.app.agent.tools.read_booking.get_current_user_uuid", return_value=None):
        from juniper_ai.app.agent.tools.read_booking import read_booking

        result = await read_booking.ainvoke({"booking_id": "JNP-ANY"})

    assert "unable to identify" in result.lower()


# ---------------------------------------------------------------------------
# Phase 2: BookingCode expiration + CountryOfResidence tests
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_book_hotel_expired_booking_code_returns_error():
    """Expired BookingCode triggers re-fetch message instead of booking."""
    from juniper_ai.app.agent.tools.book_hotel import book_hotel

    with patch("juniper_ai.app.agent.tools.book_hotel.get_current_user_id", return_value="user-1"):
        result = await book_hotel.ainvoke({
            "rate_plan_code": "RPC_001",
            "guest_name": "John Doe",
            "guest_email": "john@example.com",
            "check_in": "2026-06-15",
            "check_out": "2026-06-18",
            "booking_code": "EXPIRED_CODE",
            "booking_code_expires_at": "2020-01-01T00:00:00+00:00",
        })

    assert "expired" in result.lower()
    assert "get_booking_rules" in result.lower()


@pytest.mark.asyncio
async def test_book_hotel_valid_booking_code_proceeds():
    """Valid (not expired) BookingCode proceeds with booking."""
    from datetime import datetime, timedelta, timezone as tz

    future = (datetime.now(tz.utc) + timedelta(hours=1)).isoformat()
    mock_client = AsyncMock()
    mock_client.hotel_booking.return_value = {
        "booking_id": "BK-NEW",
        "hotel_name": "Hotel Test",
        "check_in": "2026-06-15",
        "check_out": "2026-06-18",
        "total_price": "300.00",
        "currency": "EUR",
        "status": "confirmed",
    }

    with patch("juniper_ai.app.agent.tools.book_hotel.get_juniper_client", return_value=mock_client), \
         patch("juniper_ai.app.agent.tools.book_hotel.get_current_user_id", return_value="user-1"):
        from juniper_ai.app.agent.tools.book_hotel import book_hotel

        result = await book_hotel.ainvoke({
            "rate_plan_code": "RPC_001",
            "guest_name": "John Doe",
            "guest_email": "john@example.com",
            "check_in": "2026-06-15",
            "check_out": "2026-06-18",
            "booking_code": "VALID_CODE",
            "booking_code_expires_at": future,
            "country_of_residence": "ES",
        })

    assert "BK-NEW" in result
    assert "__BOOKING_DATA__" in result
    m = re.search(r"__BOOKING_DATA__(.+?)__END_BOOKING_DATA__", result, re.DOTALL)
    payload = json.loads(m.group(1))
    assert payload["country_of_residence"] == "ES"
    assert payload["guest_name"] == "John Doe"


@pytest.mark.asyncio
async def test_book_hotel_passes_booking_code_to_client():
    """BookingCode and ExternalBookingReference are forwarded to the supplier client."""
    from datetime import datetime, timedelta, timezone as tz

    future = (datetime.now(tz.utc) + timedelta(hours=1)).isoformat()
    mock_client = AsyncMock()
    mock_client.hotel_booking.return_value = {
        "booking_id": "BK-PASS",
        "hotel_name": "Test",
        "check_in": "2026-07-01",
        "check_out": "2026-07-03",
        "total_price": "200.00",
        "currency": "EUR",
        "status": "confirmed",
    }

    with patch("juniper_ai.app.agent.tools.book_hotel.get_juniper_client", return_value=mock_client), \
         patch("juniper_ai.app.agent.tools.book_hotel.get_current_user_id", return_value="user-1"):
        from juniper_ai.app.agent.tools.book_hotel import book_hotel

        await book_hotel.ainvoke({
            "rate_plan_code": "RPC_001",
            "guest_name": "Alice Wang",
            "guest_email": "alice@test.com",
            "check_in": "2026-07-01",
            "check_out": "2026-07-03",
            "booking_code": "BC_XYZ",
            "booking_code_expires_at": future,
            "country_of_residence": "CN",
        })

    kw = mock_client.hotel_booking.await_args.kwargs
    assert kw["booking_code"] == "BC_XYZ"
    assert kw["country_of_residence"] == "CN"
    assert kw["external_booking_reference"].startswith("JA-")
    assert kw["first_name"] == "Alice"
    assert kw["surname"] == "Wang"


@pytest.mark.asyncio
async def test_booking_rules_returns_booking_code():
    """get_booking_rules tool outputs BookingCode and expiration."""
    mock_client = AsyncMock()
    mock_client.hotel_booking_rules.return_value = {
        "valid": True,
        "rate_plan_code": "RPC_001",
        "total_price": "180.00",
        "currency": "EUR",
        "cancellation_policy": "Free cancellation until 48h",
        "remarks": "",
        "booking_code": "BC_TEST_123",
        "booking_code_expires_at": "2026-06-01T12:00:00+00:00",
    }

    with patch("juniper_ai.app.agent.tools.booking_rules.get_juniper_client", return_value=mock_client):
        from juniper_ai.app.agent.tools.booking_rules import get_booking_rules

        result = await get_booking_rules.ainvoke({"rate_plan_code": "RPC_001"})

    assert "BC_TEST_123" in result
    assert "2026-06-01" in result
    assert "IMPORTANT" in result
