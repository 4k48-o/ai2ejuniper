"""§11.2 — HotelAvail request payload shape.

Locks in the wire contract that the §10 acceptance criteria depend on:

* ``@Context`` (``FULLAVAIL`` by default) is emitted as an attribute on the
  ``HotelAvailRQ`` element, **not** inside ``AdvancedOptions``.
* ``AdvancedOptions`` carries ``ShowHotelInfo`` + ``ShowCancellationPolicies``
  so the response actually contains the fields the §11.1 serializer parses.
* ``AdvancedOptions/TimeOut`` is clamped to the 8000 ms WebService ceiling
  documented in ``doc/juniper-hotel-api.md``.
"""

from datetime import date
from types import SimpleNamespace
from unittest.mock import AsyncMock, patch

import pytest

from juniper_ai.app.juniper.client import JuniperClient


@pytest.fixture
def client():
    # __init__ is a no-op (lazy WSDL). No network is touched in these tests.
    return JuniperClient()


# ------------------------- _operation_header_fields --------------------------

def test_operation_header_fields_adds_context_only_for_hotel_avail():
    fields = JuniperClient._operation_header_fields("HotelAvail")
    assert fields["Context"] == "FULLAVAIL"
    # TimeStamp also injected for avail-family ops — keep the regression lock.
    assert "TimeStamp" in fields


def test_operation_header_fields_omits_context_for_other_ops():
    # Static ops do NOT carry @Context. HotelBookingRules (§11.6) DOES —
    # docs recommend VALUATION/BOOKING/PAYMENT on that wrapper and behaviour
    # is covered in ``test_booking_rules.py``. HotelBooking (§11.8) does
    # **NOT** — UAT's WSDL rejects ``@Context`` on ``JP_HotelBooking``; see
    # ``test_hotel_booking.py::test_hotel_booking_does_not_inject_context_by_default``.
    assert "Context" not in JuniperClient._operation_header_fields("ZoneList")
    assert "Context" not in JuniperClient._operation_header_fields("CancelBooking")
    assert "Context" not in JuniperClient._operation_header_fields("ReadBooking")
    assert "Context" not in JuniperClient._operation_header_fields("HotelBooking")


def test_operation_header_fields_respects_context_override():
    """Allow per-deploy override (e.g. CACHEROBOT for a background warmer)."""
    with patch("juniper_ai.app.juniper.client.settings.juniper_avail_context", "CACHEROBOT"):
        fields = JuniperClient._operation_header_fields("HotelAvail")
    assert fields["Context"] == "CACHEROBOT"


def test_operation_header_fields_skips_context_when_blank():
    """Empty string disables the attribute entirely (opt-out escape hatch)."""
    with patch("juniper_ai.app.juniper.client.settings.juniper_avail_context", ""):
        fields = JuniperClient._operation_header_fields("HotelAvail")
    assert "Context" not in fields


# ----------------------------- _hotel_avail_batch ----------------------------

@pytest.mark.asyncio
async def test_hotel_avail_batch_sends_advanced_options(client):
    """AdvancedOptions contains the flags Juniper needs to populate name /
    cancellation info in the response (without these the §11.1 serializer
    cannot pull hotel names or refund status)."""
    fake = AsyncMock(return_value=SimpleNamespace())  # empty response → []
    with patch.object(client, "_call_with_retry", fake):
        await client._hotel_avail_batch(
            hotel_codes=["JP046300"],
            paxes=[{"IdPax": 1}],
            start_date=date(2026, 5, 1),
            end_date=date(2026, 5, 3),
            country_of_residence="ES",
            batch_index=1,
            total_batches=1,
        )

    fake.assert_awaited_once()
    call_kwargs = fake.await_args.kwargs
    advanced = call_kwargs["AdvancedOptions"]
    assert advanced["ShowHotelInfo"] is True
    assert advanced["ShowCancellationPolicies"] is True
    assert advanced["ShowOnlyAvailable"] is True
    assert advanced["TimeOut"] == 8000

    # SearchSegmentsHotels still carries HotelCodes at the correct level
    # (sibling of SearchSegmentHotels, per ticket-1096690 fix).
    ssh = call_kwargs["HotelRequest"]["SearchSegmentsHotels"]
    assert ssh["HotelCodes"] == {"HotelCode": ["JP046300"]}


@pytest.mark.asyncio
async def test_hotel_avail_batch_clamps_timeout_to_juniper_ceiling(client):
    """Juniper's WebService interface caps TimeOut at 8 seconds — the doc
    says anything higher is silently clamped server-side. We clamp locally so
    the outbound XML reflects reality and users don't get a false sense of
    security from setting 30000."""
    fake = AsyncMock(return_value=SimpleNamespace())
    with patch("juniper_ai.app.juniper.client.settings.juniper_avail_timeout_ms", 30000), \
         patch.object(client, "_call_with_retry", fake):
        await client._hotel_avail_batch(
            hotel_codes=["JP1"],
            paxes=[{"IdPax": 1}],
            start_date=date(2026, 5, 1),
            end_date=date(2026, 5, 3),
            country_of_residence="ES",
            batch_index=1,
            total_batches=1,
        )
    assert fake.await_args.kwargs["AdvancedOptions"]["TimeOut"] == 8000


@pytest.mark.asyncio
async def test_hotel_avail_batch_honours_disabled_flags(client):
    """Each flag is individually overridable — ops may want a thinner payload
    (e.g. a background cache warmer doesn't need ShowHotelInfo)."""
    fake = AsyncMock(return_value=SimpleNamespace())
    with patch("juniper_ai.app.juniper.client.settings.juniper_avail_show_hotel_info", False), \
         patch("juniper_ai.app.juniper.client.settings.juniper_avail_show_cancellation_policies", False), \
         patch("juniper_ai.app.juniper.client.settings.juniper_avail_show_only_available", False), \
         patch("juniper_ai.app.juniper.client.settings.juniper_avail_timeout_ms", 5000), \
         patch.object(client, "_call_with_retry", fake):
        await client._hotel_avail_batch(
            hotel_codes=["JP1"],
            paxes=[{"IdPax": 1}],
            start_date=date(2026, 5, 1),
            end_date=date(2026, 5, 3),
            country_of_residence="ES",
            batch_index=1,
            total_batches=1,
        )
    advanced = fake.await_args.kwargs["AdvancedOptions"]
    assert advanced == {
        "ShowHotelInfo": False,
        "ShowCancellationPolicies": False,
        "ShowOnlyAvailable": False,
        "TimeOut": 5000,
    }
