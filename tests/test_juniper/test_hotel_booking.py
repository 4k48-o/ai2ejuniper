"""§11.8 — HotelBooking request payload shape & client semantics.

Locks in the Juniper HotelBookingRQ contract documented in
``doc/juniper-hotel-api.md`` §2 and ``uploads/hotel-api-0.md`` §HotelBooking
Request. Missing any required field below causes Juniper to fail the
request with ``REQ_PRACTICE`` server-side.

Required structure:

    Paxes/Pax[*]
    Holder/RelPax/@IdPax
    Elements/HotelElement/
      BookingCode
      RelPaxesDist/RelPaxDist[*]/RelPaxes/RelPax[*]
      HotelBookingInfo/@Start/@End
      HotelBookingInfo/Price/PriceRange/@Currency/@Minimum/@Maximum
      HotelBookingInfo/HotelCode
"""

from datetime import date
from types import SimpleNamespace
from unittest.mock import AsyncMock, patch

import pytest

from juniper_ai.app.juniper.client import JuniperClient


@pytest.fixture
def client():
    return JuniperClient()


# --------------------------------------------------------------------------- #
# _operation_header_fields: @Context is NOT accepted by HotelBooking
# --------------------------------------------------------------------------- #
# The UAT WSDL signature for ``JP_HotelBooking`` (surfaced as
# ``got an unexpected keyword argument 'Context'`` during the 2026-04-23
# end-to-end smoke) confirms that ``@Context`` belongs on the availability /
# valuation wrappers only. Older revisions of this test speculated the
# opposite — keep these guards so we never re-introduce the crash.

def test_hotel_booking_does_not_inject_context_by_default():
    """HotelBooking must not carry @Context — Juniper's live WSDL rejects it."""
    fields = JuniperClient._operation_header_fields("HotelBooking")
    assert "Context" not in fields


@pytest.mark.asyncio
async def test_hotel_booking_rejects_zero_adults_when_building_paxes(client):
    with pytest.raises(ValueError, match="adults >= 1"):
        await client.hotel_booking(
            rate_plan_code="RPC",
            guest_name="Solo",
            guest_email="a@b",
            booking_code="BC",
            adults=0,
        )


def test_hotel_booking_ignores_juniper_booking_context_setting():
    """Even if operators set ``juniper_booking_context`` (legacy .env value),
    we never forward it to Juniper — the setting is kept as a no-op
    passthrough so existing .env files don't raise on startup."""
    with patch(
        "juniper_ai.app.juniper.client.settings.juniper_booking_context", "PAYMENT"
    ):
        fields = JuniperClient._operation_header_fields("HotelBooking")
    assert "Context" not in fields


# --------------------------------------------------------------------------- #
# _build_rel_paxes_dist: room→pax distribution
# --------------------------------------------------------------------------- #

def test_rel_paxes_dist_defaults_single_room_all_pax():
    result = JuniperClient._build_rel_paxes_dist([1, 2, 3])
    assert result == {
        "RelPaxDist": [
            {"RelPaxes": {"RelPax": [{"IdPax": 1}, {"IdPax": 2}, {"IdPax": 3}]}},
        ],
    }


def test_rel_paxes_dist_respects_explicit_multi_room_split():
    """Couple in room 1 + child in room 2 — docs example L889."""
    result = JuniperClient._build_rel_paxes_dist(
        [1, 2, 3],
        rel_paxes_dist=[[1], [2, 3]],
    )
    assert result == {
        "RelPaxDist": [
            {"RelPaxes": {"RelPax": [{"IdPax": 1}]}},
            {"RelPaxes": {"RelPax": [{"IdPax": 2}, {"IdPax": 3}]}},
        ],
    }


def test_rel_paxes_dist_rejects_empty_room():
    with pytest.raises(ValueError, match="RelPaxesDist rooms cannot be empty"):
        JuniperClient._build_rel_paxes_dist([1, 2], rel_paxes_dist=[[1], []])


def test_rel_paxes_dist_coerces_string_ids_to_int():
    """Mirror real paxes payloads where IdPax may come through as str."""
    result = JuniperClient._build_rel_paxes_dist([], rel_paxes_dist=[["1", "2"]])
    assert result["RelPaxDist"][0]["RelPaxes"]["RelPax"] == [
        {"IdPax": 1},
        {"IdPax": 2},
    ]


# --------------------------------------------------------------------------- #
# _build_price_range: tolerance band
# --------------------------------------------------------------------------- #

def test_price_range_strict_zero_tolerance():
    result = JuniperClient._build_price_range("1003.57", "EUR", 0.0)
    assert result == {
        "PriceRange": {
            "Currency": "EUR",
            "Minimum": "0.00",
            "Maximum": "1003.57",
        },
    }


def test_price_range_applies_positive_tolerance():
    result = JuniperClient._build_price_range("100.00", "EUR", 0.02)
    assert result["PriceRange"]["Maximum"] == "102.00"


def test_price_range_negative_tolerance_clamped_to_zero():
    """Negative tolerance shouldn't reduce Maximum below the quoted total
    (that would reject every valid booking). Treat as 0."""
    result = JuniperClient._build_price_range("100.00", "EUR", -0.5)
    assert result["PriceRange"]["Maximum"] == "100.00"


def test_price_range_returns_none_on_missing_total():
    assert JuniperClient._build_price_range(None, "EUR", 0.0) is None
    assert JuniperClient._build_price_range("", "EUR", 0.0) is None


def test_price_range_returns_none_on_invalid_total():
    assert JuniperClient._build_price_range("abc", "EUR", 0.0) is None
    assert JuniperClient._build_price_range("0", "EUR", 0.0) is None


def test_price_range_defaults_currency_when_blank():
    result = JuniperClient._build_price_range("50", "", 0.0)
    assert result["PriceRange"]["Currency"] == "EUR"


def test_price_range_accepts_float_input():
    result = JuniperClient._build_price_range(49.5, "USD", 0.0)
    assert result == {
        "PriceRange": {
            "Currency": "USD",
            "Minimum": "0.00",
            "Maximum": "49.50",
        },
    }


# --------------------------------------------------------------------------- #
# _normalize_operation_kwargs["HotelBooking"] — full payload shape
# --------------------------------------------------------------------------- #

def test_normalize_hotel_booking_emits_full_element_tree(client):
    """Every Juniper-required branch present when caller supplies them all."""
    pax = {"IdPax": 1, "Name": "John", "Surname": "Doe", "Age": 30, "Email": "j@d"}
    normalized = client._normalize_operation_kwargs(
        "HotelBooking",
        {
            "Paxes": {"Pax": [pax]},
            "Holder": {"RelPax": {"IdPax": 1}},
            "BookingCode": "BC_XYZ",
            "RelPaxesDist": {"RelPaxDist": [{"RelPaxes": {"RelPax": [{"IdPax": 1}]}}]},
            "HotelBookingInfo": {
                "Start": "2026-05-01",
                "End": "2026-05-03",
                "Price": {"PriceRange": {"Currency": "EUR", "Minimum": "0.00", "Maximum": "200.00"}},
                "HotelCode": "JP046300",
            },
            "ExternalBookingReference": "JA-DEAD",
        },
    )

    assert normalized["Paxes"] == {"Pax": [pax]}
    assert normalized["Holder"] == {"RelPax": {"IdPax": 1}}
    assert normalized["ExternalBookingReference"] == "JA-DEAD"

    element = normalized["Elements"]["HotelElement"]
    assert element["BookingCode"] == "BC_XYZ"
    assert element["RelPaxesDist"]["RelPaxDist"][0]["RelPaxes"]["RelPax"] == [
        {"IdPax": 1},
    ]
    info = element["HotelBookingInfo"]
    assert info["Start"] == "2026-05-01"
    assert info["End"] == "2026-05-03"
    assert info["HotelCode"] == "JP046300"
    assert info["Price"]["PriceRange"]["Currency"] == "EUR"
    assert info["Price"]["PriceRange"]["Maximum"] == "200.00"


def test_normalize_hotel_booking_falls_back_to_rate_plan_code(client):
    """Offline/mock path: BookingCode missing → use RatePlanCode so the XML
    still validates (Juniper rejects an empty BookingCode)."""
    normalized = client._normalize_operation_kwargs(
        "HotelBooking",
        {"Paxes": {"Pax": []}, "RatePlanCode": "RPC_123"},
    )
    assert normalized["Elements"]["HotelElement"]["BookingCode"] == "RPC_123"


def test_normalize_hotel_booking_prefers_booking_code_over_rate_plan_code(client):
    """Never accidentally send RatePlanCode as BookingCode when a real one
    is available (they are different things server-side)."""
    normalized = client._normalize_operation_kwargs(
        "HotelBooking",
        {"BookingCode": "BC_XYZ", "RatePlanCode": "RPC_123", "Paxes": {"Pax": []}},
    )
    assert normalized["Elements"]["HotelElement"]["BookingCode"] == "BC_XYZ"


def test_normalize_hotel_booking_skips_optional_nodes_when_absent(client):
    """Holder / RelPaxesDist / HotelBookingInfo / ExternalBookingReference /
    Comments are all omitted from the XML when the caller hasn't supplied
    them — keeps the payload minimal for legacy code paths (§11.8 adds
    these fields, but we don't force them on every caller)."""
    normalized = client._normalize_operation_kwargs(
        "HotelBooking",
        {"BookingCode": "BC", "Paxes": {"Pax": []}},
    )
    element = normalized["Elements"]["HotelElement"]
    assert "RelPaxesDist" not in element
    assert "HotelBookingInfo" not in element
    assert "ExternalBookingReference" not in normalized
    assert "Comments" not in normalized
    assert "Holder" not in normalized


def test_normalize_hotel_booking_passes_through_comments(client):
    normalized = client._normalize_operation_kwargs(
        "HotelBooking",
        {
            "BookingCode": "BC",
            "Paxes": {"Pax": []},
            "Comments": {"Comment": [{"Type": "RES", "_value_1": "Late check-in"}]},
        },
    )
    assert normalized["Comments"]["Comment"][0]["_value_1"] == "Late check-in"


# --------------------------------------------------------------------------- #
# JuniperClient.hotel_booking — integration of helpers into the SOAP call
# --------------------------------------------------------------------------- #

@pytest.mark.asyncio
async def test_hotel_booking_builds_paxes_from_adults_children(client):
    """Occupancy in HotelBooking must match HotelAvail or Juniper returns
    JP_BOOK_OCCUPANCY_ERROR (UAT 2026-04-23)."""
    fake = AsyncMock(return_value=SimpleNamespace())
    with patch.object(client, "_call_with_retry", fake):
        await client.hotel_booking(
            rate_plan_code="RPC_999",
            guest_name="John Doe",
            guest_email="j@d.com",
            booking_code="BC_XYZ",
            hotel_code="JP046300",
            check_in="2026-05-01",
            check_out="2026-05-03",
            total_price="150.00",
            currency="EUR",
            country_of_residence="ES",
            adults=2,
            children=1,
        )
    kwargs = fake.await_args.kwargs
    pax_list = kwargs["Paxes"]["Pax"]
    assert len(pax_list) == 3
    assert [p["IdPax"] for p in pax_list] == [1, 2, 3]
    assert pax_list[0]["Email"] == "j@d.com"
    assert pax_list[0]["Nationality"] == "ES"
    assert pax_list[1]["Name"] == "Guest"
    assert pax_list[2]["Age"] == 8
    dist = kwargs["RelPaxesDist"]["RelPaxDist"][0]["RelPaxes"]["RelPax"]
    assert dist == [{"IdPax": 1}, {"IdPax": 2}, {"IdPax": 3}]


@pytest.mark.asyncio
async def test_hotel_booking_builds_full_soap_payload(client):
    """End-to-end: caller passes agent-level args, the method hydrates the
    full Juniper payload — Holder/RelPax/@IdPax, RelPaxesDist, HotelBookingInfo."""
    fake = AsyncMock(return_value=SimpleNamespace())  # empty body → empty dict
    with patch.object(client, "_call_with_retry", fake):
        await client.hotel_booking(
            rate_plan_code="RPC_999",
            guest_name="John Doe",
            guest_email="j@d.com",
            booking_code="BC_XYZ",
            hotel_code="JP046300",
            check_in=date(2026, 5, 1),
            check_out=date(2026, 5, 3),
            total_price="150.00",
            currency="EUR",
            country_of_residence="ES",
            external_booking_reference="JA-IDEMPOTENCY",
        )

    fake.assert_awaited_once()
    kwargs = fake.await_args.kwargs

    # Holder references pax #1 (docs L887: Holder/RelPax/@IdPax is required)
    assert kwargs["Holder"] == {"RelPax": {"IdPax": 1}}

    # Paxes has the holder with nationality from country_of_residence
    pax_list = kwargs["Paxes"]["Pax"]
    assert len(pax_list) == 1
    assert pax_list[0]["IdPax"] == 1
    assert pax_list[0]["Name"] == "John"
    assert pax_list[0]["Surname"] == "Doe"
    assert pax_list[0]["Email"] == "j@d.com"
    assert pax_list[0]["Nationality"] == "ES"

    # RelPaxesDist built from the default single-room split
    assert kwargs["RelPaxesDist"]["RelPaxDist"][0]["RelPaxes"]["RelPax"] == [
        {"IdPax": 1},
    ]

    # HotelBookingInfo carries the full verification block
    info = kwargs["HotelBookingInfo"]
    assert info["Start"] == "2026-05-01"
    assert info["End"] == "2026-05-03"
    assert info["HotelCode"] == "JP046300"
    assert info["Price"]["PriceRange"]["Maximum"] == "150.00"
    assert info["Price"]["PriceRange"]["Currency"] == "EUR"

    assert kwargs["BookingCode"] == "BC_XYZ"
    assert kwargs["ExternalBookingReference"] == "JA-IDEMPOTENCY"


@pytest.mark.asyncio
async def test_hotel_booking_accepts_iso_string_dates(client):
    """Agent tool passes `check_in`/`check_out` as YYYY-MM-DD strings — both
    `date` objects and strings must work (strings are the common agent path)."""
    fake = AsyncMock(return_value=SimpleNamespace())
    with patch.object(client, "_call_with_retry", fake):
        await client.hotel_booking(
            rate_plan_code="RPC_999",
            guest_name="Jane Roe",
            guest_email="j@r.com",
            booking_code="BC",
            hotel_code="JP1",
            check_in="2026-05-01",
            check_out="2026-05-03",
            total_price="50",
            currency="EUR",
        )
    info = fake.await_args.kwargs["HotelBookingInfo"]
    assert info["Start"] == "2026-05-01"
    assert info["End"] == "2026-05-03"


@pytest.mark.asyncio
async def test_hotel_booking_supports_explicit_multi_pax_multi_room(client):
    """3-pax / 2-room stay (couple + child). Exercises explicit `paxes` +
    `rel_paxes_dist` overrides — matches docs example L889."""
    paxes = [
        {"IdPax": 1, "Name": "John", "Surname": "Doe", "Age": 50, "Email": "j@d"},
        {"IdPax": 2, "Name": "Jane", "Surname": "Roe", "Age": 45},
        {"IdPax": 3, "Name": "Jr", "Surname": "Doe", "Age": 8},
    ]
    fake = AsyncMock(return_value=SimpleNamespace())
    with patch.object(client, "_call_with_retry", fake):
        await client.hotel_booking(
            rate_plan_code="RPC_MULTI",
            guest_name="John Doe",
            guest_email="j@d",
            booking_code="BC_MULTI",
            hotel_code="JP1",
            check_in="2026-06-01",
            check_out="2026-06-04",
            total_price="800",
            currency="EUR",
            paxes=paxes,
            rel_paxes_dist=[[1], [2, 3]],
        )
    kwargs = fake.await_args.kwargs
    assert kwargs["Paxes"]["Pax"] == paxes
    assert kwargs["Holder"] == {"RelPax": {"IdPax": 1}}

    rooms = kwargs["RelPaxesDist"]["RelPaxDist"]
    assert len(rooms) == 2
    assert rooms[0]["RelPaxes"]["RelPax"] == [{"IdPax": 1}]
    assert rooms[1]["RelPaxes"]["RelPax"] == [{"IdPax": 2}, {"IdPax": 3}]


@pytest.mark.asyncio
async def test_hotel_booking_omits_hotel_booking_info_when_unknown(client):
    """Legacy callers that only have a BookingCode (no hotel_code/dates/
    price) still produce a syntactically valid payload — Juniper will
    reject it server-side but we don't crash locally."""
    fake = AsyncMock(return_value=SimpleNamespace())
    with patch.object(client, "_call_with_retry", fake):
        await client.hotel_booking(
            rate_plan_code="RPC_LEGACY",
            guest_name="Solo",
            guest_email="s@s",
            booking_code="BC_LEGACY",
        )
    kwargs = fake.await_args.kwargs
    assert "HotelBookingInfo" not in kwargs


@pytest.mark.asyncio
async def test_hotel_booking_logs_warning_when_booking_code_missing(client, caplog):
    """No BookingCode → we fall back to RatePlanCode AND log a warning, so
    operators can see when the agent forgot to call get_booking_rules."""
    fake = AsyncMock(return_value=SimpleNamespace())
    with caplog.at_level("WARNING", logger="juniper_ai.app.juniper.client"), \
         patch.object(client, "_call_with_retry", fake):
        await client.hotel_booking(
            rate_plan_code="RPC_NO_BC",
            guest_name="John",
            guest_email="j@d",
        )
    assert any(
        "HotelBooking called without BookingCode" in m for m in caplog.messages
    )
    assert fake.await_args.kwargs["RatePlanCode"] == "RPC_NO_BC"


@pytest.mark.asyncio
async def test_hotel_booking_price_range_honours_tolerance_setting(client):
    """§11.8 tolerance knob: PriceRange/@Maximum = total * (1 + tolerance)."""
    fake = AsyncMock(return_value=SimpleNamespace())
    with patch(
        "juniper_ai.app.juniper.client.settings.juniper_booking_price_tolerance_pct",
        0.05,
    ), patch.object(client, "_call_with_retry", fake):
        await client.hotel_booking(
            rate_plan_code="RPC_PT",
            guest_name="John",
            guest_email="j@d",
            booking_code="BC",
            hotel_code="JP1",
            check_in="2026-05-01",
            check_out="2026-05-03",
            total_price="100.00",
            currency="EUR",
        )
    info = fake.await_args.kwargs["HotelBookingInfo"]
    assert info["Price"]["PriceRange"]["Maximum"] == "105.00"


@pytest.mark.asyncio
async def test_hotel_booking_skips_price_node_when_total_invalid(client):
    """Invalid total → we don't invent a PriceRange (better to let Juniper
    reject with a readable error than send bogus bounds)."""
    fake = AsyncMock(return_value=SimpleNamespace())
    with patch.object(client, "_call_with_retry", fake):
        await client.hotel_booking(
            rate_plan_code="RPC",
            guest_name="John",
            guest_email="j@d",
            booking_code="BC",
            hotel_code="JP1",
            check_in="2026-05-01",
            check_out="2026-05-03",
            total_price="not-a-number",
            currency="EUR",
        )
    info = fake.await_args.kwargs.get("HotelBookingInfo", {})
    assert "Price" not in info
