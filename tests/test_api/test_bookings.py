"""Tests for Booking API routes."""

import uuid
from datetime import datetime, timezone
from unittest.mock import AsyncMock, MagicMock

import pytest
from httpx import ASGITransport, AsyncClient

from juniper_ai.app.api.middleware.auth import AuthContext
from juniper_ai.app.db.models import BookingStatus
from juniper_ai.app.main import app


def _fake_booking(status: BookingStatus, **kwargs):
    booking = MagicMock()
    booking.id = kwargs.get("id", uuid.uuid4())
    booking.juniper_booking_id = kwargs.get("juniper_booking_id", "JNP-BOOK001")
    booking.status = status
    booking.hotel_name = kwargs.get("hotel_name", "NH Collection Barcelona")
    booking.check_in = kwargs.get("check_in", "2026-04-10")
    booking.check_out = kwargs.get("check_out", "2026-04-12")
    booking.total_price = kwargs.get("total_price", "180.00")
    booking.currency = kwargs.get("currency", "EUR")
    booking.created_at = kwargs.get("created_at", datetime.now(timezone.utc))
    return booking


def _stmt_from_list_bookings_execute(mock_db: AsyncMock) -> str:
    stmt = mock_db.execute.await_args.args[0]
    return str(stmt)


def _setup_list_bookings_get(bookings_list, user_id: str = "test-user"):
    mock_db = AsyncMock()
    result = MagicMock()
    result.scalars.return_value.all.return_value = bookings_list
    mock_db.execute = AsyncMock(return_value=result)
    mock_db.commit = AsyncMock()
    mock_db.rollback = AsyncMock()
    auth = AuthContext(user_id=user_id, auth_type="jwt")
    return mock_db, auth


@pytest.mark.asyncio
async def test_list_bookings_ordered_by_created_at_desc():
    """BOOK-01: query uses ORDER BY created_at DESC; response order follows DB rows."""
    base = datetime(2026, 3, 1, 12, 0, 0, tzinfo=timezone.utc)
    older = _fake_booking(BookingStatus.confirmed, created_at=base)
    newer = _fake_booking(BookingStatus.confirmed, created_at=base.replace(day=15))
    mock_db, auth = _setup_list_bookings_get([newer, older])

    from juniper_ai.app.db.session import get_db
    from juniper_ai.app.api.middleware.auth import get_auth_context

    app.dependency_overrides[get_db] = lambda: mock_db
    app.dependency_overrides[get_auth_context] = lambda: auth

    try:
        async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
            response = await client.get("/api/v1/bookings")
        assert response.status_code == 200
        sql = _stmt_from_list_bookings_execute(mock_db)
        assert "ORDER BY bookings.created_at DESC" in sql
        data = response.json()
        assert [item["id"] for item in data] == [str(newer.id), str(older.id)]
    finally:
        app.dependency_overrides.clear()


@pytest.mark.asyncio
async def test_list_bookings_empty_for_user():
    """BOOK-02: no rows → []."""
    mock_db, auth = _setup_list_bookings_get([])

    from juniper_ai.app.db.session import get_db
    from juniper_ai.app.api.middleware.auth import get_auth_context

    app.dependency_overrides[get_db] = lambda: mock_db
    app.dependency_overrides[get_auth_context] = lambda: auth

    try:
        async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
            response = await client.get("/api/v1/bookings")
        assert response.status_code == 200
        assert response.json() == []
    finally:
        app.dependency_overrides.clear()


@pytest.mark.asyncio
async def test_list_bookings_response_has_all_fields():
    """BOOK-03: BookingResponse keys populated from ORM row."""
    bid = uuid.uuid4()
    created = datetime(2026, 2, 1, 8, 30, 0, tzinfo=timezone.utc)
    booking = _fake_booking(
        BookingStatus.modified,
        id=bid,
        juniper_booking_id="JNP-ABCDEF12",
        hotel_name="Test Hotel",
        check_in="2026-05-01",
        check_out="2026-05-05",
        total_price="220.50",
        currency="USD",
        created_at=created,
    )
    mock_db, auth = _setup_list_bookings_get([booking])

    from juniper_ai.app.db.session import get_db
    from juniper_ai.app.api.middleware.auth import get_auth_context

    app.dependency_overrides[get_db] = lambda: mock_db
    app.dependency_overrides[get_auth_context] = lambda: auth

    try:
        async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
            response = await client.get("/api/v1/bookings")
        assert response.status_code == 200
        item = response.json()[0]
        expected_keys = {
            "id",
            "juniper_booking_id",
            "status",
            "hotel_name",
            "check_in",
            "check_out",
            "total_price",
            "currency",
            "created_at",
        }
        assert set(item.keys()) == expected_keys
        assert item["id"] == str(bid)
        assert item["juniper_booking_id"] == "JNP-ABCDEF12"
        assert item["status"] == "modified"
        assert item["hotel_name"] == "Test Hotel"
        assert item["check_in"] == "2026-05-01"
        assert item["check_out"] == "2026-05-05"
        assert item["total_price"] == "220.50"
        assert item["currency"] == "USD"
        assert item["created_at"].startswith("2026-02-01T08:30:00")
    finally:
        app.dependency_overrides.clear()


@pytest.mark.asyncio
async def test_list_bookings_query_scoped_to_authenticated_user():
    """BOOK-04: SELECT joins users and filters external_id (no cross-user rows from ORM)."""
    mock_db, auth = _setup_list_bookings_get([], user_id="tenant-xyz")

    from juniper_ai.app.db.session import get_db
    from juniper_ai.app.api.middleware.auth import get_auth_context

    app.dependency_overrides[get_db] = lambda: mock_db
    app.dependency_overrides[get_auth_context] = lambda: auth

    try:
        async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
            response = await client.get("/api/v1/bookings")
        assert response.status_code == 200
        sql = _stmt_from_list_bookings_execute(mock_db).lower()
        assert "join users" in sql
        assert "users.external_id" in sql
        assert "bookings" in sql
    finally:
        app.dependency_overrides.clear()


@pytest.mark.asyncio
async def test_list_bookings_reflects_updated_status():
    booking = _fake_booking(BookingStatus.cancelled)

    mock_db = AsyncMock()
    result = MagicMock()
    result.scalars.return_value.all.return_value = [booking]
    mock_db.execute = AsyncMock(return_value=result)
    mock_db.commit = AsyncMock()
    mock_db.rollback = AsyncMock()

    auth = AuthContext(user_id="test-user", auth_type="jwt")

    from juniper_ai.app.db.session import get_db
    from juniper_ai.app.api.middleware.auth import get_auth_context

    app.dependency_overrides[get_db] = lambda: mock_db
    app.dependency_overrides[get_auth_context] = lambda: auth

    try:
        async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
            response = await client.get("/api/v1/bookings")
        assert response.status_code == 200
        data = response.json()
        assert len(data) == 1
        assert data[0]["status"] == "cancelled"
        assert data[0]["juniper_booking_id"] == "JNP-BOOK001"
    finally:
        app.dependency_overrides.clear()


def _setup_get_booking_one(booking_or_none, user_id: str = "test-user"):
    mock_db = AsyncMock()
    result = MagicMock()
    result.scalar_one_or_none.return_value = booking_or_none
    mock_db.execute = AsyncMock(return_value=result)
    mock_db.commit = AsyncMock()
    mock_db.rollback = AsyncMock()
    auth = AuthContext(user_id=user_id, auth_type="jwt")
    return mock_db, auth


@pytest.mark.asyncio
async def test_get_booking_by_id_returns_full_detail():
    """BOOK-05: existing booking → 200 and full BookingResponse."""
    bid = uuid.uuid4()
    created = datetime(2026, 1, 10, 10, 0, 0, tzinfo=timezone.utc)
    booking = _fake_booking(
        BookingStatus.confirmed,
        id=bid,
        juniper_booking_id="JNP-GETBOOK1",
        hotel_name="Grand Hotel",
        check_in="2026-06-01",
        check_out="2026-06-03",
        total_price="99.00",
        currency="GBP",
        created_at=created,
    )
    mock_db, auth = _setup_get_booking_one(booking)

    from juniper_ai.app.db.session import get_db
    from juniper_ai.app.api.middleware.auth import get_auth_context

    app.dependency_overrides[get_db] = lambda: mock_db
    app.dependency_overrides[get_auth_context] = lambda: auth

    try:
        async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
            response = await client.get(f"/api/v1/bookings/{bid}")
        assert response.status_code == 200
        item = response.json()
        assert set(item.keys()) == {
            "id",
            "juniper_booking_id",
            "status",
            "hotel_name",
            "check_in",
            "check_out",
            "total_price",
            "currency",
            "created_at",
        }
        assert item["id"] == str(bid)
        assert item["juniper_booking_id"] == "JNP-GETBOOK1"
        assert item["status"] == "confirmed"
        assert item["hotel_name"] == "Grand Hotel"
        assert item["check_in"] == "2026-06-01"
        assert item["check_out"] == "2026-06-03"
        assert item["total_price"] == "99.00"
        assert item["currency"] == "GBP"
        assert item["created_at"].startswith("2026-01-10T10:00:00")
    finally:
        app.dependency_overrides.clear()


@pytest.mark.asyncio
async def test_get_booking_unknown_id_returns_404():
    """BOOK-06: no matching row → 404 + generic message."""
    booking_id = uuid.uuid4()
    mock_db, auth = _setup_get_booking_one(None)

    from juniper_ai.app.db.session import get_db
    from juniper_ai.app.api.middleware.auth import get_auth_context

    app.dependency_overrides[get_db] = lambda: mock_db
    app.dependency_overrides[get_auth_context] = lambda: auth

    try:
        async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
            response = await client.get(f"/api/v1/bookings/{booking_id}")
        assert response.status_code == 404
        assert response.json()["detail"] == "Booking not found"
    finally:
        app.dependency_overrides.clear()


@pytest.mark.asyncio
async def test_get_booking_other_user_returns_404():
    """AUTH-12 / MULTI-04 / BOOK-07: other user's id → same 404 as unknown (no 403)."""
    booking_id = uuid.uuid4()
    mock_db = AsyncMock()
    result = MagicMock()
    result.scalar_one_or_none.return_value = None
    mock_db.execute = AsyncMock(return_value=result)

    auth = AuthContext(user_id="user-a", auth_type="jwt")

    from juniper_ai.app.db.session import get_db
    from juniper_ai.app.api.middleware.auth import get_auth_context

    app.dependency_overrides[get_db] = lambda: mock_db
    app.dependency_overrides[get_auth_context] = lambda: auth

    try:
        async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
            response = await client.get(f"/api/v1/bookings/{booking_id}")
        assert response.status_code == 404
        assert response.json()["detail"] == "Booking not found"
    finally:
        app.dependency_overrides.clear()

