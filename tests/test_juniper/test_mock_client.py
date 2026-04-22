"""Tests for the mock Juniper client."""

import re

import pytest

from juniper_ai.app.juniper.exceptions import BookingOwnershipError, RoomUnavailableError
from juniper_ai.app.juniper.mock_client import MOCK_BOOKINGS, MockJuniperClient


@pytest.fixture
def client():
    MOCK_BOOKINGS.clear()
    return MockJuniperClient()


@pytest.mark.asyncio
async def test_hotel_avail_returns_results(client):
    hotels = await client.hotel_avail("49435", "2026-04-15", "2026-04-18")
    assert len(hotels) > 0
    assert all("name" in h for h in hotels)
    assert all("total_price" in h for h in hotels)
    assert all("rate_plan_code" in h for h in hotels)


@pytest.mark.asyncio
async def test_hotel_avail_returns_all_for_any_zone(client):
    hotels = await client.hotel_avail("99999", "2026-04-15", "2026-04-18")
    assert len(hotels) == 5  # mock returns all hotels regardless of zone


@pytest.mark.asyncio
async def test_hotel_avail_filters_by_hotel_codes(client):
    """Primary path — hotel_codes filters MOCK_HOTELS by hotel_code (case-insensitive)."""
    hotels = await client.hotel_avail(
        hotel_codes=["hot001", "HOT003", "UNKNOWN_CODE"],
        check_in="2026-04-15",
        check_out="2026-04-18",
    )
    codes = {h["hotel_code"] for h in hotels}
    assert codes == {"HOT001", "HOT003"}


@pytest.mark.asyncio
async def test_hotel_avail_without_any_input_raises(client):
    """At least one of hotel_codes or zone_code is required (matches abstract contract)."""
    with pytest.raises(ValueError, match="hotel_codes"):
        await client.hotel_avail(check_in="2026-04-15", check_out="2026-04-18")


@pytest.mark.asyncio
async def test_hotel_avail_hotel_codes_with_filters(client):
    """hotel_codes + star_rating combine (JPCode filter first, then post-filters)."""
    hotels = await client.hotel_avail(
        hotel_codes=["HOT001", "HOT002", "HOT003", "HOT004", "HOT005"],
        check_in="2026-04-15",
        check_out="2026-04-18",
        star_rating=5,
    )
    assert len(hotels) >= 1
    assert all("5" in h["category"] for h in hotels)


@pytest.mark.asyncio
async def test_hotel_check_avail_valid_code(client):
    result = await client.hotel_check_avail("RPC_001_DBL_BB")
    assert result["available"] is True
    assert result["total_price"] == "180.00"


@pytest.mark.asyncio
async def test_hotel_check_avail_invalid_code(client):
    with pytest.raises(RoomUnavailableError):
        await client.hotel_check_avail("INVALID_CODE")


@pytest.mark.asyncio
async def test_hotel_booking_rules(client):
    rules = await client.hotel_booking_rules("RPC_001_DBL_BB")
    assert rules["valid"] is True
    assert "cancellation_policy" in rules


_JNP_BOOKING_ID_RE = re.compile(r"^JNP-[0-9A-F]{8}$")


@pytest.mark.asyncio
async def test_hotel_booking_id_matches_jnp_format(client):
    """BOOK-09: mock supplier returns booking_id as JNP- + 8 hex digits (uppercase)."""
    booking = await client.hotel_booking(
        rate_plan_code="RPC_001_DBL_BB",
        guest_name="John Doe",
        guest_email="john@example.com",
    )
    assert _JNP_BOOKING_ID_RE.match(booking["booking_id"])


@pytest.mark.asyncio
async def test_hotel_booking_flow(client):
    # Book
    booking = await client.hotel_booking(
        rate_plan_code="RPC_001_DBL_BB",
        guest_name="John Doe",
        guest_email="john@example.com",
    )
    assert booking["status"] == "confirmed"
    assert _JNP_BOOKING_ID_RE.match(booking["booking_id"])
    booking_id = booking["booking_id"]

    # Read
    details = await client.read_booking(booking_id)
    assert details["status"] == "confirmed"

    # Cancel
    cancel_result = await client.cancel_booking(booking_id)
    assert cancel_result["status"] == "cancelled"


@pytest.mark.asyncio
async def test_modify_booking(client):
    # Book first
    booking = await client.hotel_booking("RPC_001_DBL_BB", "Jane Doe", "jane@example.com")
    booking_id = booking["booking_id"]

    # Modify
    result = await client.hotel_modify(booking_id, check_in="2026-04-20", check_out="2026-04-23")
    assert result.get("check_in") == "2026-04-20"


# ---------------------------------------------------------------------------
# Cross-user booking isolation tests
# ---------------------------------------------------------------------------


@pytest.fixture
async def bob_booking(client):
    """Create a booking owned by bob."""
    booking = await client.hotel_booking(
        "RPC_001_DBL_BB", "Bob", "bob@test.com", user_id="user-bob",
    )
    return booking["booking_id"]


@pytest.mark.asyncio
async def test_read_booking_cross_user_raises_ownership_error(client, bob_booking):
    """Alice cannot read Bob's booking."""
    with pytest.raises(BookingOwnershipError):
        await client.read_booking(bob_booking, user_id="user-alice")


@pytest.mark.asyncio
async def test_read_booking_same_user_succeeds(client, bob_booking):
    """Bob can read his own booking."""
    result = await client.read_booking(bob_booking, user_id="user-bob")
    assert result["booking_id"] == bob_booking


@pytest.mark.asyncio
async def test_cancel_booking_cross_user_raises_ownership_error(client, bob_booking):
    """Alice cannot cancel Bob's booking."""
    with pytest.raises(BookingOwnershipError):
        await client.cancel_booking(bob_booking, user_id="user-alice")


@pytest.mark.asyncio
async def test_cancel_booking_same_user_succeeds(client, bob_booking):
    """Bob can cancel his own booking."""
    result = await client.cancel_booking(bob_booking, user_id="user-bob")
    assert result["status"] == "cancelled"


@pytest.mark.asyncio
async def test_modify_booking_cross_user_raises_ownership_error(client, bob_booking):
    """Alice cannot modify Bob's booking."""
    with pytest.raises(BookingOwnershipError):
        await client.hotel_modify(bob_booking, user_id="user-alice", check_in="2026-05-01")


@pytest.mark.asyncio
async def test_modify_booking_same_user_succeeds(client, bob_booking):
    """Bob can modify his own booking."""
    result = await client.hotel_modify(bob_booking, user_id="user-bob", check_in="2026-05-01")
    assert result["check_in"] == "2026-05-01"


@pytest.mark.asyncio
async def test_list_bookings_filters_by_user(client):
    """Each user only sees their own bookings."""
    await client.hotel_booking("RPC_001_DBL_BB", "Bob", "bob@test.com", user_id="user-bob")
    await client.hotel_booking("RPC_002_SUP_RO", "Alice", "alice@test.com", user_id="user-alice")

    bob_bookings = await client.list_bookings(user_id="user-bob")
    alice_bookings = await client.list_bookings(user_id="user-alice")

    assert all(b.get("user_id") == "user-bob" for b in bob_bookings)
    assert all(b.get("user_id") == "user-alice" for b in alice_bookings)
    # No overlap
    bob_ids = {b["booking_id"] for b in bob_bookings}
    alice_ids = {b["booking_id"] for b in alice_bookings}
    assert bob_ids.isdisjoint(alice_ids)
