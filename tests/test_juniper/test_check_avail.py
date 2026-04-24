"""§11.4 — HotelCheckAvail request + error semantics.

Covers the three error paths in ``JuniperClient.hotel_check_avail`` plus
the request-shape contract (``@Context`` attribute, optional
``SearchSegmentsHotels`` verification block).
"""

from datetime import date
from types import SimpleNamespace
from unittest.mock import AsyncMock, patch

import pytest

from juniper_ai.app.juniper.client import JuniperClient
from juniper_ai.app.juniper.exceptions import (
    PriceChangedError,
    RoomUnavailableError,
)


# ---------------------------------------------------------------------------
# Fixtures — zeep-shaped CheckAvailRS builders
# ---------------------------------------------------------------------------


def _option(rpc: str, status: str, gross: str, currency: str = "EUR") -> SimpleNamespace:
    total_fix = SimpleNamespace(Gross=gross, Nett=gross, Service=None, ServiceTaxes=None)
    price = SimpleNamespace(Currency=currency, Type="S", TotalFixAmounts=total_fix)
    return SimpleNamespace(
        RatePlanCode=rpc,
        Status=status,
        Board=SimpleNamespace(Type="SA", _value_1="Room Only"),
        Prices=SimpleNamespace(Price=[price]),
        HotelRooms=None,
    )


def _response(options, warnings=None):
    if options is None:
        results = None
    else:
        hr = SimpleNamespace(HotelOptions=SimpleNamespace(HotelOption=options))
        results = SimpleNamespace(HotelResult=hr)
    warnings_node = (
        SimpleNamespace(Warning=[SimpleNamespace(Code=c, Text=t) for c, t in warnings])
        if warnings else None
    )
    return SimpleNamespace(Results=results, Warnings=warnings_node)


@pytest.fixture
def client():
    return JuniperClient()


# ---------------------------------------------------------------------------
# _operation_header_fields — SINGLEAVAIL context on HotelCheckAvailRQ
# ---------------------------------------------------------------------------


def test_check_avail_context_attribute_defaults_to_singleavail():
    fields = JuniperClient._operation_header_fields("HotelCheckAvail")
    assert fields["Context"] == "SINGLEAVAIL"
    assert "TimeStamp" in fields


def test_check_avail_context_respects_override_and_disable():
    with patch("juniper_ai.app.juniper.client.settings.juniper_check_avail_context", "VALUATION"):
        assert JuniperClient._operation_header_fields("HotelCheckAvail")["Context"] == "VALUATION"
    # Empty string disables the attribute.
    with patch("juniper_ai.app.juniper.client.settings.juniper_check_avail_context", ""):
        assert "Context" not in JuniperClient._operation_header_fields("HotelCheckAvail")


# ---------------------------------------------------------------------------
# Request-shape: SearchSegmentsHotels verification block
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_hotel_check_avail_sends_search_segments_when_dates_provided(client):
    """Dates + hotel_code → SearchSegmentsHotels verification block so Juniper
    can cross-check the RatePlanCode against the original search window."""
    response = _response([_option("RPC_NEW", "OK", "100.00")])
    with patch.object(client, "_call_with_retry", AsyncMock(return_value=response)) as fake:
        result = await client.hotel_check_avail(
            "RPC_OLD",
            check_in=date(2026, 6, 1),
            check_out=date(2026, 6, 5),
            hotel_code="JP046300",
        )

    assert result["rate_plan_code"] == "RPC_NEW"
    kwargs = fake.await_args.kwargs
    # Internal kwargs passed through — normalization happens in _call_with_retry.
    assert kwargs["RatePlanCode"] == "RPC_OLD"
    ss = kwargs["SearchSegmentsHotels"]
    # Zeep dual-slot shape: ``_value_1`` for the JP_SearchSegmentBase content
    # model, duplicated at top-level so zeep's date serializer can populate
    # the @Start / @End attributes without crashing on NotSet (UAT 2026-04-23).
    assert ss["SearchSegmentHotels"] == {
        "_value_1": {"Start": "2026-06-01", "End": "2026-06-05"},
        "Start": "2026-06-01",
        "End": "2026-06-05",
    }
    assert ss["HotelCodes"] == {"HotelCode": ["JP046300"]}


@pytest.mark.asyncio
async def test_hotel_check_avail_omits_search_segments_when_not_provided(client):
    """Legacy callers that only have a RatePlanCode still work — the
    verification block is optional per docs."""
    response = _response([_option("RPC_NEW", "OK", "100.00")])
    with patch.object(client, "_call_with_retry", AsyncMock(return_value=response)) as fake:
        await client.hotel_check_avail("RPC_OLD")

    assert fake.await_args.kwargs["SearchSegmentsHotels"] is None


# ---------------------------------------------------------------------------
# Error semantics — three paths per §11.4
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_hotel_check_avail_price_changed_raises_with_new_rate_plan_code(client):
    """warnPriceChanged in response → PriceChangedError carries the new
    RatePlanCode so the caller can retry the booking flow (per docs
    §HotelCheckAvail Response)."""
    response = _response(
        [_option("RPC_NEW_PRICE", "OK", "250.00")],
        warnings=[("warnPriceChanged", "Price changed; use new RatePlanCode")],
    )
    with patch.object(client, "_call_with_retry", AsyncMock(return_value=response)):
        with pytest.raises(PriceChangedError) as exc_info:
            await client.hotel_check_avail(
                "RPC_OLD",
                expected_price="200.00",
            )

    err = exc_info.value
    assert err.old_price == "200.00"
    assert err.new_price == "250.00"
    assert err.currency == "EUR"
    assert err.new_rate_plan_code == "RPC_NEW_PRICE"


@pytest.mark.asyncio
async def test_hotel_check_avail_price_changed_without_expected_price_uses_unknown(client):
    response = _response(
        [_option("RPC_NEW", "OK", "250.00")],
        warnings=[("warnPriceChanged", "Price changed")],
    )
    with patch.object(client, "_call_with_retry", AsyncMock(return_value=response)):
        with pytest.raises(PriceChangedError) as exc_info:
            await client.hotel_check_avail("RPC_OLD")
    assert exc_info.value.old_price == "unknown"


@pytest.mark.asyncio
async def test_hotel_check_avail_rq_only_raises_room_unavailable(client):
    """No OK option → RoomUnavailableError (supplier has stock but it's on
    request — not bookable in our flow)."""
    response = _response([_option("RPC_RQ", "RQ", "100.00")])
    with patch.object(client, "_call_with_retry", AsyncMock(return_value=response)):
        with pytest.raises(RoomUnavailableError, match="status=RQ"):
            await client.hotel_check_avail("RPC_OLD")


@pytest.mark.asyncio
async def test_hotel_check_avail_no_options_raises_room_unavailable(client):
    """Empty Results → RoomUnavailableError."""
    response = _response(None)
    with patch.object(client, "_call_with_retry", AsyncMock(return_value=response)):
        with pytest.raises(RoomUnavailableError):
            await client.hotel_check_avail("RPC_OLD")


@pytest.mark.asyncio
async def test_hotel_check_avail_status_changed_raises_room_unavailable(client):
    """warnStatusChanged alone → treat as unavailable; the "OK" status on the
    option is stale per docs."""
    response = _response(
        [_option("RPC_NEW", "OK", "200.00")],
        warnings=[("warnStatusChanged", "Availability changed")],
    )
    with patch.object(client, "_call_with_retry", AsyncMock(return_value=response)):
        with pytest.raises(RoomUnavailableError):
            await client.hotel_check_avail("RPC_OLD")


@pytest.mark.asyncio
async def test_hotel_check_avail_check_not_possible_raises_room_unavailable(client):
    """warnCheckNotPossible → supplier couldn't verify; safest to bail."""
    response = _response(
        None,
        warnings=[("warnCheckNotPossible", "Could not verify")],
    )
    with patch.object(client, "_call_with_retry", AsyncMock(return_value=response)):
        with pytest.raises(RoomUnavailableError, match="warnCheckNotPossible"):
            await client.hotel_check_avail("RPC_OLD")


@pytest.mark.asyncio
async def test_hotel_check_avail_ok_returns_new_rate_plan_code(client):
    """Happy path: returns the NEW RatePlanCode from the response so the
    caller drives HotelBookingRules / HotelBooking with the fresh code."""
    response = _response([_option("RPC_NEW_CODE", "OK", "300.00")])
    with patch.object(client, "_call_with_retry", AsyncMock(return_value=response)):
        result = await client.hotel_check_avail("RPC_OLD_CODE")
    assert result["available"] is True
    assert result["rate_plan_code"] == "RPC_NEW_CODE"
    assert result["total_price"] == "300.00"
    assert result["currency"] == "EUR"
