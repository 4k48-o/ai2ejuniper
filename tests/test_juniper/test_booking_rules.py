"""§11.6 — HotelBookingRules request + error semantics.

Covers:

* ``@Context`` attribute on ``HotelBookingRulesRQ`` (defaults to
  ``VALUATION`` per docs, override-able via settings).
* ``SearchSegmentsHotels`` verification block — pass-through shape.
* ``_normalize_operation_kwargs`` for HotelBookingRules wrapping.
* Error semantics in ``JuniperClient.hotel_booking_rules``:
    - ``warnCheckNotPossible`` → RoomUnavailableError
    - ``warnPriceChanged`` → PriceChangedError (with ``new_rate_plan_code``)
    - ``warnStatusChanged`` or ``@Status != OK`` → RoomUnavailableError
    - missing ``BookingCode`` → RoomUnavailableError (the point of the call)
* Happy-path returns the refreshed RatePlanCode + BookingCode + expiry.
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
# Fixtures — zeep-shaped BookingRulesRS builders
# ---------------------------------------------------------------------------


def _make_prices(gross: str, currency: str = "EUR") -> SimpleNamespace:
    total_fix = SimpleNamespace(
        Gross=gross, Nett=gross, Service=None, ServiceTaxes=None,
    )
    price = SimpleNamespace(Currency=currency, Type="S", TotalFixAmounts=total_fix)
    return SimpleNamespace(Price=[price])


def _make_booking_rules_option(
    *,
    rate_plan_code: str = "RPC_NEW",
    status: str = "OK",
    gross: str = "1003.57",
    currency: str = "EUR",
    booking_code: str = "BC_ABC",
    expires: str = "2019-10-03T09:46:30+02:00",
) -> SimpleNamespace:
    """Minimum-shape HotelOption the serializer needs to succeed. Extra
    fields (HotelContent / RequiredFields / OptionalElements) are left
    absent — their absence must not crash the client error-detection
    layer."""
    price_info = SimpleNamespace(
        Board=SimpleNamespace(Type="AD", _value_1="Bed & Breakfast"),
        HotelRooms=None,
        Prices=_make_prices(gross, currency),
        AdditionalElements=None,
        HotelContent=None,
    )
    return SimpleNamespace(
        Status=status,
        RatePlanCode=rate_plan_code,
        BookingCode=SimpleNamespace(_value_1=booking_code, ExpirationDate=expires),
        HotelRequiredFields=None,
        CancellationPolicy=None,
        PriceInformation=price_info,
        OptionalElements=None,
    )


def _make_response(
    options: list[SimpleNamespace] | None,
    warnings: list[tuple[str, str]] | None = None,
) -> SimpleNamespace:
    """Build a BookingRulesRS mirror:
    * ``options=None`` → no Results at all.
    * ``options=[]``   → HotelOptions container empty.
    """
    if options is None:
        results = None
    else:
        hr = SimpleNamespace(
            HotelOptions=SimpleNamespace(
                HotelOption=options if len(options) != 1 else options[0]
            )
        )
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
# _operation_header_fields — VALUATION @Context on HotelBookingRulesRQ
# ---------------------------------------------------------------------------


def test_booking_rules_context_attribute_defaults_to_valuation():
    """Docs §HotelBookingRules Request (line 2495) recommend
    VALUATION/BOOKING/PAYMENT — default to VALUATION so Juniper routes
    through the valuation pool rather than the availability one."""
    fields = JuniperClient._operation_header_fields("HotelBookingRules")
    assert fields["Context"] == "VALUATION"
    # TimeStamp injected for check/book-family ops — lock the regression.
    assert "TimeStamp" in fields


def test_booking_rules_context_respects_override():
    with patch("juniper_ai.app.juniper.client.settings.juniper_booking_rules_context", "BOOKING"):
        fields = JuniperClient._operation_header_fields("HotelBookingRules")
    assert fields["Context"] == "BOOKING"


def test_booking_rules_context_disabled_when_blank():
    """Empty string disables the attribute (escape hatch for suppliers
    that reject unexpected @Context values)."""
    with patch("juniper_ai.app.juniper.client.settings.juniper_booking_rules_context", ""):
        fields = JuniperClient._operation_header_fields("HotelBookingRules")
    assert "Context" not in fields


# ---------------------------------------------------------------------------
# _normalize_operation_kwargs — wraps payload under HotelBookingRulesRequest
# ---------------------------------------------------------------------------


def test_normalize_booking_rules_minimal_payload(client):
    """Just a RatePlanCode → HotelBookingRulesRequest/HotelOption/@RatePlanCode."""
    payload = client._normalize_operation_kwargs(
        "HotelBookingRules", {"RatePlanCode": "RPC_X"}
    )
    assert payload == {
        "HotelBookingRulesRequest": {"HotelOption": {"RatePlanCode": "RPC_X"}}
    }


def test_normalize_booking_rules_includes_search_segments_when_provided(client):
    """SearchSegmentsHotels is optional per docs but strongly recommended —
    when supplied it must land *inside* HotelBookingRulesRequest alongside
    HotelOption, not at the RQ root."""
    search_segments = {
        "SearchSegmentHotels": {"Start": "2026-06-01", "End": "2026-06-05"},
        "HotelCodes": {"HotelCode": ["JP046300"]},
    }
    payload = client._normalize_operation_kwargs(
        "HotelBookingRules",
        {"RatePlanCode": "RPC_X", "SearchSegmentsHotels": search_segments},
    )
    request = payload["HotelBookingRulesRequest"]
    assert request["HotelOption"] == {"RatePlanCode": "RPC_X"}
    assert request["SearchSegmentsHotels"] == search_segments


def test_normalize_booking_rules_passes_advanced_options(client):
    """AdvancedOptions (e.g. ShowBreakdownPrice / PromoCode) must sit at
    the RQ root per docs, not inside HotelBookingRulesRequest."""
    payload = client._normalize_operation_kwargs(
        "HotelBookingRules",
        {"RatePlanCode": "RPC_X", "AdvancedOptions": {"ShowBreakdownPrice": True}},
    )
    assert payload["AdvancedOptions"] == {"ShowBreakdownPrice": True}
    # HotelBookingRulesRequest is untouched.
    assert "AdvancedOptions" not in payload["HotelBookingRulesRequest"]


# ---------------------------------------------------------------------------
# Request-shape: SearchSegmentsHotels verification block (via client method)
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_hotel_booking_rules_sends_search_segments_when_dates_provided(client):
    """dates + hotel_code → Juniper cross-checks the RatePlanCode against
    the original search window (uploads/hotel-api-0.md §Request lines
    2501-2508). If they drift the supplier returns ``warnCheckNotPossible``."""
    response = _make_response([_make_booking_rules_option()])
    with patch.object(client, "_call_with_retry", AsyncMock(return_value=response)) as fake:
        result = await client.hotel_booking_rules(
            "RPC_OLD",
            check_in=date(2026, 6, 1),
            check_out=date(2026, 6, 5),
            hotel_code="JP046300",
        )

    assert result["rate_plan_code"] == "RPC_NEW"
    kwargs = fake.await_args.kwargs
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
async def test_hotel_booking_rules_omits_search_segments_when_not_provided(client):
    """Legacy callers with only a RatePlanCode still work — verification
    block is optional per docs."""
    response = _make_response([_make_booking_rules_option()])
    with patch.object(client, "_call_with_retry", AsyncMock(return_value=response)) as fake:
        await client.hotel_booking_rules("RPC_OLD")

    assert fake.await_args.kwargs["SearchSegmentsHotels"] is None


@pytest.mark.asyncio
async def test_hotel_booking_rules_accepts_iso_date_strings(client):
    """Agent tool passes dates as ISO strings; must not be re-formatted."""
    response = _make_response([_make_booking_rules_option()])
    with patch.object(client, "_call_with_retry", AsyncMock(return_value=response)) as fake:
        await client.hotel_booking_rules(
            "RPC_X", check_in="2026-06-01", check_out="2026-06-05",
        )
    ss = fake.await_args.kwargs["SearchSegmentsHotels"]
    assert ss["SearchSegmentHotels"] == {
        "_value_1": {"Start": "2026-06-01", "End": "2026-06-05"},
        "Start": "2026-06-01",
        "End": "2026-06-05",
    }


# ---------------------------------------------------------------------------
# Error semantics — mirrors §11.4 HotelCheckAvail
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_hotel_booking_rules_price_changed_raises_with_new_rate_plan_code(client):
    """warnPriceChanged → PriceChangedError carries the new RatePlanCode so
    the caller can retry the booking flow (docs §HotelBookingRules
    Response, warnings)."""
    response = _make_response(
        [_make_booking_rules_option(rate_plan_code="RPC_UPDATED", gross="1100.00")],
        warnings=[("warnPriceChanged", "Price changed; use new RatePlanCode")],
    )
    with patch.object(client, "_call_with_retry", AsyncMock(return_value=response)):
        with pytest.raises(PriceChangedError) as exc_info:
            await client.hotel_booking_rules(
                "RPC_OLD", expected_price="1003.57",
            )

    err = exc_info.value
    assert err.old_price == "1003.57"
    assert err.new_price == "1100.00"
    assert err.currency == "EUR"
    assert err.new_rate_plan_code == "RPC_UPDATED"


@pytest.mark.asyncio
async def test_hotel_booking_rules_price_changed_without_expected_price_uses_unknown(client):
    response = _make_response(
        [_make_booking_rules_option(rate_plan_code="RPC_NEW")],
        warnings=[("warnPriceChanged", "Price changed")],
    )
    with patch.object(client, "_call_with_retry", AsyncMock(return_value=response)):
        with pytest.raises(PriceChangedError) as exc_info:
            await client.hotel_booking_rules("RPC_OLD")
    assert exc_info.value.old_price == "unknown"


@pytest.mark.asyncio
async def test_hotel_booking_rules_rq_only_raises_room_unavailable(client):
    """@Status=RQ → serializer marks valid=False → client raises."""
    response = _make_response([_make_booking_rules_option(status="RQ")])
    with patch.object(client, "_call_with_retry", AsyncMock(return_value=response)):
        with pytest.raises(RoomUnavailableError, match="status=RQ"):
            await client.hotel_booking_rules("RPC_OLD")


@pytest.mark.asyncio
async def test_hotel_booking_rules_no_options_raises_room_unavailable(client):
    """Empty Results → status="" → RoomUnavailableError."""
    response = _make_response(None)
    with patch.object(client, "_call_with_retry", AsyncMock(return_value=response)):
        with pytest.raises(RoomUnavailableError):
            await client.hotel_booking_rules("RPC_OLD")


@pytest.mark.asyncio
async def test_hotel_booking_rules_status_changed_raises_room_unavailable(client):
    """warnStatusChanged: allotment dropped from OK to something unsellable.
    Even when the raw @Status is still 'OK', docs say treat as stale."""
    response = _make_response(
        [_make_booking_rules_option(status="OK")],
        warnings=[("warnStatusChanged", "Availability changed")],
    )
    with patch.object(client, "_call_with_retry", AsyncMock(return_value=response)):
        with pytest.raises(RoomUnavailableError):
            await client.hotel_booking_rules("RPC_OLD")


@pytest.mark.asyncio
async def test_hotel_booking_rules_check_not_possible_raises_room_unavailable(client):
    """warnCheckNotPossible → supplier couldn't verify; safest to bail.
    Note: this error is raised BEFORE looking at price_changed, since we
    don't trust any of the response data when verification fails."""
    response = _make_response(
        [_make_booking_rules_option()],
        warnings=[("warnCheckNotPossible", "Could not verify")],
    )
    with patch.object(client, "_call_with_retry", AsyncMock(return_value=response)):
        with pytest.raises(RoomUnavailableError, match="warnCheckNotPossible"):
            await client.hotel_booking_rules("RPC_OLD")


@pytest.mark.asyncio
async def test_hotel_booking_rules_missing_booking_code_raises_room_unavailable(client):
    """The whole point of HotelBookingRules is to get a BookingCode. If
    the supplier returns an OK option without one, HotelBooking cannot
    proceed — fail loudly rather than returning a useless dict."""
    opt = _make_booking_rules_option()
    opt.BookingCode = None
    response = _make_response([opt])
    with patch.object(client, "_call_with_retry", AsyncMock(return_value=response)):
        with pytest.raises(RoomUnavailableError, match="no BookingCode"):
            await client.hotel_booking_rules("RPC_OLD")


@pytest.mark.asyncio
async def test_hotel_booking_rules_ok_returns_refreshed_rate_plan_code_and_booking_code(client):
    """Happy path: Juniper may regenerate the RatePlanCode even on a clean
    OK response. Always return HotelOption/@RatePlanCode from the response —
    NOT the input code — so subsequent HotelBooking uses the fresh code."""
    response = _make_response([
        _make_booking_rules_option(
            rate_plan_code="RPC_REFRESHED",
            booking_code="BC_FRESH_123",
            expires="2026-06-01T12:00:00+00:00",
        )
    ])
    with patch.object(client, "_call_with_retry", AsyncMock(return_value=response)):
        result = await client.hotel_booking_rules("RPC_OLD_CODE")

    assert result["valid"] is True
    assert result["rate_plan_code"] == "RPC_REFRESHED"
    assert result["booking_code"] == "BC_FRESH_123"
    assert result["booking_code_expires_at"] == "2026-06-01T12:00:00+00:00"


@pytest.mark.asyncio
async def test_hotel_booking_rules_warn_ordering_check_not_possible_beats_price_changed(client):
    """When the response somehow carries BOTH warnings, verification
    failure wins — we can't trust the new price either."""
    response = _make_response(
        [_make_booking_rules_option(rate_plan_code="RPC_NEW", gross="1100.00")],
        warnings=[
            ("warnCheckNotPossible", "Could not verify"),
            ("warnPriceChanged", "Price changed"),
        ],
    )
    with patch.object(client, "_call_with_retry", AsyncMock(return_value=response)):
        with pytest.raises(RoomUnavailableError, match="warnCheckNotPossible"):
            await client.hotel_booking_rules("RPC_OLD", expected_price="1003.57")


# ---------------------------------------------------------------------------
# _build_search_segments_hotels — shared helper with HotelCheckAvail
# ---------------------------------------------------------------------------


def test_build_search_segments_hotels_returns_none_when_all_inputs_absent():
    assert JuniperClient._build_search_segments_hotels(None, None, None) is None


def test_build_search_segments_hotels_omits_empty_inner_blocks():
    """hotel_code alone → HotelCodes present, SearchSegmentHotels absent
    (docs allow either sub-node independently)."""
    block = JuniperClient._build_search_segments_hotels(None, None, "JP046300")
    assert block == {"HotelCodes": {"HotelCode": ["JP046300"]}}
    assert "SearchSegmentHotels" not in block


def test_build_search_segments_hotels_formats_date_objects():
    """``datetime.date`` inputs are ISO-8601 formatted; strings pass through."""
    block = JuniperClient._build_search_segments_hotels(
        date(2026, 6, 1), "2026-06-05", "JP046300",
    )
    # Dual-slot shape — see _build_search_segments_hotels docstring (UAT 2026-04-23)
    assert block["SearchSegmentHotels"] == {
        "_value_1": {"Start": "2026-06-01", "End": "2026-06-05"},
        "Start": "2026-06-01",
        "End": "2026-06-05",
    }
