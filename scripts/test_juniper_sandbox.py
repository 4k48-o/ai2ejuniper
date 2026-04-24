#!/usr/bin/env python3
"""Smoke-test Juniper xml-uat SOAP (Flicknmix credentials).

Modes:
  * ``--mode=hotelcodes`` (default) — post-ticket-1096690 path.
    Resolves test zones (15011 / 13826) to JPCodes via the **local
    static cache** (requires ``python scripts/run_static_data_sync.py``
    to have been run at least once), then calls ``HotelAvail`` with
    ``HotelCodes=[...]``. Prints request summary + per-city result /
    ``fault_code``. This is the happy path that the current agent uses.
  * ``--mode=legacy`` — old ``DestinationZone`` path. Will return
    ``REQ_PRACTICE`` for the ``TestXMLFlicknmix`` account (see
    ``doc/email/juniper-support-ticket-email-zh.md``); kept to
    reproduce the original bug for Juniper support tickets.

Booking-flow flags (only meaningful with ``--mode=hotelcodes``):
  * ``--full-booking`` — after ``HotelAvail`` picks an OK option, run
    ``HotelCheckAvail`` + ``HotelBookingRules`` against its
    ``RatePlanCode``. These two endpoints are **idempotent / side-effect
    free** and are the standard pre-booking valuation path.
  * ``--confirm-booking`` — implies ``--full-booking`` and additionally
    runs ``HotelBooking`` with a synthetic test guest, creating a **real
    reservation** in Juniper's UAT environment. Use sparingly; the
    locator is printed so the reservation can be reconciled or
    cancelled later via ``CancelBooking``.
  * ``--persist-db`` — after a successful ``HotelBooking``, insert a row
    into PostgreSQL ``bookings`` (same shape as agent ``book_hotel`` →
    ``_persist_booking``). Requires ``DATABASE_URL``, ``--confirm-booking``,
    and a working UAT chain. Creates a stub ``users`` row (see
    ``--sandbox-external-user-id``) and a synthetic ``conversations`` row.

Prerequisites:
  - ``.env`` with JUNIPER_USE_MOCK=false, JUNIPER_API_URL, JUNIPER_EMAIL,
    JUNIPER_PASSWORD.
  - For ``hotelcodes`` mode: DB reachable + static sync run previously.
  - Run from repo root:  python scripts/test_juniper_sandbox.py

Supplier test zones (JP code / DestinationZone):
  - Palma de Mallorca: 15011  (Juniper-confirmed JPCode JP046300)
  - Dubai City: 13826
"""

from __future__ import annotations

import argparse
import asyncio
import sys
import uuid
from datetime import date, datetime, timedelta, timezone
from pathlib import Path

_ROOT = Path(__file__).resolve().parents[1]
if str(_ROOT) not in sys.path:
    sys.path.insert(0, str(_ROOT))

from sqlalchemy import select

from juniper_ai.app.config import settings
from juniper_ai.app.db.models import Conversation, ConversationStatus, Zone
from juniper_ai.app.db.session import async_session
from juniper_ai.app.services.booking_persist import persist_booking_record
from juniper_ai.app.services.users import get_or_create_user_by_external_id
from juniper_ai.app.juniper.client import JuniperClient
from juniper_ai.app.juniper.exceptions import (
    JuniperFaultError,
    NoResultsError,
    PriceChangedError,
    RoomUnavailableError,
)
from juniper_ai.app.juniper.static_data import list_hotels_in_zone_jpdcodes


TEST_ZONES = [
    ("Palma de Mallorca", "15011"),
    ("Dubai City", "13826"),
]


async def _persist_sandbox_booking_to_db(
    *,
    external_user_id: str,
    booking: dict,
    rate_plan_code: str,
    guest_name: str,
    guest_email: str,
    country: str,
    external_booking_reference: str,
) -> tuple[uuid.UUID, uuid.UUID, uuid.UUID]:
    """Mirror agent ``book_hotel`` → ``persist_booking_record`` (``bookings`` table).

    Returns ``(bookings.id, conversations.id, users.id)``.
    """
    booking_data = {
        "__booking__": True,
        "booking_id": booking.get("booking_id"),
        "hotel_name": booking.get("hotel_name"),
        "check_in": booking.get("check_in"),
        "check_out": booking.get("check_out"),
        "total_price": booking.get("total_price"),
        "currency": booking.get("currency"),
        "status": booking.get("status"),
        "rate_plan_code": rate_plan_code,
        "guest_name": guest_name,
        "guest_email": guest_email,
        "country_of_residence": country,
        "external_booking_reference": external_booking_reference,
    }
    async with async_session() as db:
        try:
            user = await get_or_create_user_by_external_id(db, external_user_id)
            conv = Conversation(
                user_id=user.id,
                status=ConversationStatus.active,
                state={"source": "test_juniper_sandbox"},
                language="en",
                expires_at=datetime.now(timezone.utc) + timedelta(hours=24),
            )
            db.add(conv)
            await db.flush()
            row_id = await persist_booking_record(
                db,
                user_id=user.id,
                conversation_id=conv.id,
                booking_data=booking_data,
            )
            if row_id is None:
                raise RuntimeError(
                    "persist_booking_record skipped insert (duplicate idempotency key)"
                )
            await db.commit()
            return row_id, conv.id, user.id
        except Exception:
            await db.rollback()
            raise


class _SoapDumper:
    """Optional zeep ``HistoryPlugin`` wrapper that writes the last
    request/response XML to disk per sandbox step.

    Attached only when ``--debug-soap`` is passed. The goal is to diagnose
    cases where every JPCode legitimately returns ``NO_AVAIL_FOUND`` vs.
    cases where the serializer is dropping valid inventory — two very
    different root causes that look identical from the script output.
    """

    def __init__(self, client: JuniperClient, out_dir: Path) -> None:
        self._out_dir = out_dir
        self._out_dir.mkdir(parents=True, exist_ok=True)
        from zeep.plugins import HistoryPlugin  # local import to keep import path lazy

        self._history = HistoryPlugin()
        client._ensure_client()  # noqa: SLF001 — sandbox tool, deliberate
        client._client.plugins.append(self._history)  # noqa: SLF001
        self._run_stamp = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")

    @staticmethod
    def _envelope_to_str(envelope: object) -> str:
        if envelope is None:
            return "<no envelope captured>"
        try:
            from lxml import etree

            return etree.tostring(envelope, pretty_print=True).decode()
        except Exception as exc:  # noqa: BLE001
            return f"<failed to render envelope: {exc!r}>"

    def dump(self, label: str) -> Path | None:
        sent = getattr(self._history, "last_sent", None)
        received = getattr(self._history, "last_received", None)
        if not sent and not received:
            return None
        safe = "".join(ch if ch.isalnum() or ch in "-_" else "_" for ch in label)
        out_path = self._out_dir / f"{self._run_stamp}_{safe}.xml"
        lines = [
            f"<!-- Juniper SOAP dump — {label} -->",
            "<!-- ===== REQUEST ===== -->",
            self._envelope_to_str((sent or {}).get("envelope")),
            "<!-- ===== RESPONSE ===== -->",
            self._envelope_to_str((received or {}).get("envelope")),
        ]
        out_path.write_text("\n".join(lines), encoding="utf-8")
        print(f"  soap_dump: {out_path}")
        return out_path

# Juniper support explicitly confirmed JP046300 returns availability for
# Palma (see juniper-support-ticket-email-zh.md). Used as a last-resort
# fallback when the local cache has not been synced for this zone.
KNOWN_GOOD_JPCODES = {
    "15011": ["JP046300"],
}

# Keep the sandbox SOAP round-trip tiny — this is a smoke test, not a load test.
SANDBOX_CODES_PER_ZONE = 5


def _mask_password(raw: str) -> str:
    if not raw:
        return ""
    if len(raw) <= 4:
        return "*" * len(raw)
    return f"{raw[:2]}***{raw[-2:]}"


async def _resolve_jpcodes_for_zone(
    zone_code: str,
    *,
    limit: int,
    prepend_known_good: bool,
) -> tuple[str, list[str], str]:
    """Return (jpdcode, jpcodes, source). ``source`` is one of
    ``known-good``, ``cache``, ``fallback-no-zone``, ``fallback-empty-cache``.
    """
    seed = KNOWN_GOOD_JPCODES.get(zone_code, [])
    async with async_session() as db:
        row = await db.execute(
            select(Zone).where(Zone.code == zone_code).limit(1)
        )
        zone = row.scalar_one_or_none()
        if not zone:
            return ("", list(seed), "fallback-no-zone")

        codes = await list_hotels_in_zone_jpdcodes(
            db, [zone.jpdcode],
            limit=limit,
            expand_descendants=True,
            only_jpcodes=True,
        )
        if prepend_known_good and seed:
            # Dedup while preserving order: seed first, then cache fills remaining slots.
            seen: set[str] = set()
            merged: list[str] = []
            for c in list(seed) + list(codes):
                if c not in seen:
                    seen.add(c)
                    merged.append(c)
                    if len(merged) >= limit:
                        break
            return (zone.jpdcode, merged, "known-good")
        if codes:
            return (zone.jpdcode, list(codes), "cache")
        # DB knows the zone but no hotels cached — fall back if we have a seed.
        return (zone.jpdcode, list(seed), "fallback-empty-cache")


def _pick_cheapest_ok_option(hotels: list[dict]) -> dict | None:
    """Select the cheapest ``status=OK`` row from a ``HotelAvail`` result.

    ``hotel_avail`` returns one row per HotelOption (§11.3), so "cheapest
    OK row" is exactly the cheapest bookable combination. Falls back to
    ``None`` when no OK row exists so the caller can short-circuit the
    booking chain rather than crashing downstream.
    """
    candidates = [h for h in hotels if (h.get("status") or "").upper() == "OK"]
    if not candidates:
        return None

    def gross(row: dict) -> float:
        try:
            return float(row.get("total_price") or "inf")
        except (TypeError, ValueError):
            return float("inf")

    return min(candidates, key=gross)


async def _run_full_booking_chain(
    client: JuniperClient,
    picked: dict,
    *,
    city_name: str,
    zone_code: str,
    check_in: str,
    check_out: str,
    country: str,
    adults: int,
    children: int,
    confirm_booking: bool,
    soap_dumper: _SoapDumper | None,
    persist_db: bool = False,
    sandbox_external_user_id: str = "sandbox-uat-persist",
) -> bool:
    """Drive ``HotelCheckAvail → HotelBookingRules (→ HotelBooking)``.

    The chain mirrors the Juniper canonical booking flow (see
    ``uploads/hotel-api-0.md`` §Booking Integration Process):

      1. ``HotelCheckAvail`` revalidates the ``RatePlanCode`` and
         surfaces any ``warnPriceChanged`` / ``warnStatusChanged``.
      2. ``HotelBookingRules`` performs the real pre-booking valuation
         and returns the ``BookingCode`` (10-min TTL) plus the
         definitive cancellation policy + required pax fields.
      3. Optionally ``HotelBooking`` commits a real reservation against
         UAT using a synthetic guest (``sandbox-<uuid>@juniperai.test``).

    Returns ``True`` on a clean run (including the case where
    HotelCheckAvail / Rules cleanly surfaced a recoverable error); only
    unexpected exceptions return ``False``.
    """
    rate_plan_code = picked.get("rate_plan_code") or ""
    hotel_code = picked.get("jpcode") or picked.get("hotel_code") or ""
    total_price = picked.get("total_price")
    currency = picked.get("currency") or "EUR"
    if not rate_plan_code:
        print("  [full-booking] skipped: picked option has no RatePlanCode")
        return False

    print(
        f"\n  [full-booking] picked: hotel_code={hotel_code} "
        f"rate_plan_code={rate_plan_code[:32]}... price={total_price} {currency}"
    )

    # ---- HotelCheckAvail -------------------------------------------------
    print("  [HotelCheckAvail] revalidating rate plan ...")
    try:
        check = await client.hotel_check_avail(
            rate_plan_code,
            check_in=check_in,
            check_out=check_out,
            hotel_code=hotel_code,
            expected_price=str(total_price) if total_price is not None else None,
        )
    except PriceChangedError as exc:
        print(f"    WARN: warnPriceChanged — old={exc.old_price} new={exc.new_price} {exc.currency}")
        print(f"    using refreshed RatePlanCode={exc.new_rate_plan_code[:32]}... for next step")
        rate_plan_code = exc.new_rate_plan_code or rate_plan_code
        total_price = exc.new_price
        currency = exc.currency or currency
    except RoomUnavailableError as exc:
        print(f"    status=ROOM_UNAVAILABLE ({exc})")
        if soap_dumper is not None:
            soap_dumper.dump(f"HotelCheckAvail-UNAVAIL-{city_name}-{zone_code}")
        return True
    except JuniperFaultError as exc:
        print(f"    status=FAULT code={exc.fault_code} msg={exc.fault_string}")
        if soap_dumper is not None:
            soap_dumper.dump(f"HotelCheckAvail-FAULT-{city_name}-{zone_code}")
        return False
    else:
        if soap_dumper is not None:
            soap_dumper.dump(f"HotelCheckAvail-OK-{city_name}-{zone_code}")
        print(
            f"    OK status={check.get('status')} "
            f"total={check.get('total_price')} {check.get('currency')} "
            f"board={(check.get('board') or {}).get('type') or '-'} "
            f"warnings={check.get('warning_codes') or []}"
        )
        # Docs §HotelCheckAvail Response: use the RatePlanCode FROM the
        # response on subsequent calls (the caller's original code is now
        # stale).
        rate_plan_code = check.get("rate_plan_code") or rate_plan_code
        if check.get("total_price") and check["total_price"] != "0":
            total_price = check["total_price"]
            currency = check.get("currency") or currency

    # ---- HotelBookingRules ----------------------------------------------
    print("  [HotelBookingRules] pre-booking valuation ...")
    try:
        rules = await client.hotel_booking_rules(
            rate_plan_code,
            check_in=check_in,
            check_out=check_out,
            hotel_code=hotel_code,
            expected_price=str(total_price) if total_price is not None else None,
        )
    except PriceChangedError as exc:
        print(f"    WARN: warnPriceChanged — old={exc.old_price} new={exc.new_price} {exc.currency}")
        print(f"    refreshed RatePlanCode={exc.new_rate_plan_code[:32]}... — aborting chain, rerun to retry")
        if soap_dumper is not None:
            soap_dumper.dump(f"HotelBookingRules-PRICECHANGED-{city_name}-{zone_code}")
        return True
    except RoomUnavailableError as exc:
        print(f"    status=ROOM_UNAVAILABLE ({exc})")
        if soap_dumper is not None:
            soap_dumper.dump(f"HotelBookingRules-UNAVAIL-{city_name}-{zone_code}")
        return True
    except JuniperFaultError as exc:
        print(f"    status=FAULT code={exc.fault_code} msg={exc.fault_string}")
        if soap_dumper is not None:
            soap_dumper.dump(f"HotelBookingRules-FAULT-{city_name}-{zone_code}")
        return False

    if soap_dumper is not None:
        soap_dumper.dump(f"HotelBookingRules-OK-{city_name}-{zone_code}")

    booking_code = rules.get("booking_code") or ""
    expires = rules.get("booking_code_expires_at") or ""
    new_rpc = rules.get("rate_plan_code") or rate_plan_code
    total_price = rules.get("total_price") or total_price
    currency = rules.get("currency") or currency
    cancel_rules = len(((rules.get("cancellation") or {}).get("rules")) or [])
    print(
        f"    OK valid={rules.get('valid')} total={total_price} {currency} "
        f"booking_code={booking_code[:20]}... expires_at={expires or '-'} "
        f"cancel_rules={cancel_rules} warnings={rules.get('warning_codes') or []}"
    )
    required_fields = rules.get("required_fields") or {}
    if required_fields:
        # Surface the bits HotelBooking actually cares about so the
        # operator knows whether the synthetic pax is rich enough.
        keys = sorted(k for k, v in required_fields.items() if v)
        print(f"    required_fields(set)={keys[:8]}")

    if not confirm_booking:
        print("  [HotelBooking] SKIPPED (pass --confirm-booking to actually book)")
        return True

    if not booking_code:
        print("  [HotelBooking] ABORTED — BookingRules did not return a BookingCode")
        return False

    # ---- HotelBooking (creates a real UAT reservation) ------------------
    idempotency_key = f"sandbox-{uuid.uuid4().hex[:12]}"
    synthetic_email = f"{idempotency_key}@juniperai.test"
    print(
        f"  [HotelBooking] committing reservation hotel={hotel_code} "
        f"total={total_price} {currency} idempotency={idempotency_key}"
    )
    try:
        booking = await client.hotel_booking(
            rate_plan_code=new_rpc,
            guest_name="Sandbox Tester",
            guest_email=synthetic_email,
            booking_code=booking_code,
            hotel_code=hotel_code,
            check_in=check_in,
            check_out=check_out,
            total_price=total_price,
            currency=currency,
            first_name="Sandbox",
            surname="Tester",
            country_of_residence=country,
            adults=adults,
            children=children,
            external_booking_reference=idempotency_key,
        )
    except JuniperFaultError as exc:
        print(f"    status=FAULT code={exc.fault_code} msg={exc.fault_string}")
        if soap_dumper is not None:
            soap_dumper.dump(f"HotelBooking-FAULT-{city_name}-{zone_code}")
        return False
    except Exception as exc:  # noqa: BLE001
        print(f"    status=ERROR type={type(exc).__name__} msg={exc!r}")
        if soap_dumper is not None:
            soap_dumper.dump(f"HotelBooking-ERROR-{city_name}-{zone_code}")
        return False

    if soap_dumper is not None:
        soap_dumper.dump(f"HotelBooking-OK-{city_name}-{zone_code}")
    print(
        f"    OK booking_id={booking.get('booking_id')} "
        f"status={booking.get('status')} "
        f"total={booking.get('total_price')} {booking.get('currency')} "
        f"guest={booking.get('guest_name')}"
    )
    print(
        f"    TIP: reconcile / cancel with"
        f" `python -c 'import asyncio;"
        f"from juniper_ai.app.juniper.client import JuniperClient;"
        f"print(asyncio.run(JuniperClient().cancel_booking(\"{booking.get('booking_id')}\")))'`"
    )

    if persist_db:
        guest_name = "Sandbox Tester"
        print(
            "  [DB] persisting row into bookings (users + conversations stub) "
            f"external_user_id={sandbox_external_user_id!r} ..."
        )
        try:
            bid, cid, uid = await _persist_sandbox_booking_to_db(
                external_user_id=sandbox_external_user_id,
                booking=booking,
                rate_plan_code=new_rpc,
                guest_name=guest_name,
                guest_email=synthetic_email,
                country=country,
                external_booking_reference=idempotency_key,
            )
        except Exception as exc:  # noqa: BLE001
            print(f"    DB: FAILED {type(exc).__name__}: {exc}")
            return False
        print(
            f"    DB: OK bookings.id={bid} conversation_id={cid} "
            f"user.id={uid} juniper_booking_id={booking.get('booking_id')}"
        )
    return True


async def _run_hotelcodes_mode(
    client: JuniperClient,
    *,
    codes_per_zone: int,
    use_known_good: bool,
    full_booking: bool = False,
    confirm_booking: bool = False,
    soap_dumper: _SoapDumper | None = None,
    persist_db: bool = False,
    sandbox_external_user_id: str = "sandbox-uat-persist",
) -> int:
    ci = (date.today() + timedelta(days=45)).isoformat()
    co = (date.today() + timedelta(days=48)).isoformat()
    adults = 2
    children = 0
    country = "ES"
    all_ok = True

    print("\n--- HotelAvail dual-city (HotelCodes mode, ticket-1096690 compliant) ---")
    print(
        "Request summary:",
        {
            "check_in": ci, "check_out": co,
            "adults": adults, "children": children,
            "country_of_residence": country,
            "zones": [{"name": n, "code": c} for n, c in TEST_ZONES],
            "codes_per_zone_cap": codes_per_zone,
            "use_known_good": use_known_good,
            # Surface the AdvancedOptions so the output is self-documenting
            # when we forward it to Juniper support.
            "context": settings.juniper_avail_context,
            "show_hotel_info": settings.juniper_avail_show_hotel_info,
            "show_cancellation_policies": settings.juniper_avail_show_cancellation_policies,
            "show_only_available": settings.juniper_avail_show_only_available,
            "timeout_ms": settings.juniper_avail_timeout_ms,
        },
    )

    for city_name, zone_code in TEST_ZONES:
        jpdcode, jpcodes, source = await _resolve_jpcodes_for_zone(
            zone_code,
            limit=codes_per_zone,
            prepend_known_good=use_known_good,
        )
        print(
            f"\n[HotelAvail] city={city_name} zone_code={zone_code} "
            f"jpdcode={jpdcode or '?'} source={source} jpcodes={jpcodes}"
        )
        if not jpcodes:
            all_ok = False
            print(
                "  status=SKIPPED — no JPCodes available. "
                "Run `python scripts/run_static_data_sync.py` to populate the cache."
            )
            continue

        picked_row: dict | None = None
        try:
            hotels = await client.hotel_avail(
                hotel_codes=jpcodes,
                check_in=ci, check_out=co,
                adults=adults, children=children,
                country_of_residence=country,
            )
            if soap_dumper is not None:
                soap_dumper.dump(f"HotelAvail-{city_name}-{zone_code}")
            print(f"  status=OK, hotels={len(hotels)}")
            if full_booking or confirm_booking:
                picked_row = _pick_cheapest_ok_option(hotels)
            # After §11.1/§11.2/§11.3, each item is one expanded HotelOption
            # (not one HotelResult) — surface the new structured fields so
            # we can eyeball that ShowHotelInfo / ShowCancellationPolicies
            # / warnings took. ``refundable`` is the derived tri-state from
            # HotelOption/@NonRefundable (True / False / None=unknown).
            for h in hotels[:3]:
                name = h.get("name") or f"<no-name {h.get('hotel_code')}>"
                avail_status = h.get("status") or "?"
                board = h.get("board_name") or h.get("board_type") or "-"
                rate = h.get("rate_plan_code") or "-"
                room_count = len(h.get("rooms") or [])
                cancel_rules = len((h.get("cancellation") or {}).get("rules") or [])
                warn_codes = h.get("warning_codes") or []
                print(
                    "   ", name,
                    "|", h.get("total_price"), h.get("currency"),
                    "| status=", avail_status,
                    "| board=", board,
                    "| rate=", rate,
                    "| rooms=", room_count,
                    "| refundable=", h.get("refundable"),
                    "| cancel_rules=", cancel_rules,
                )
                if warn_codes:
                    print("    warnings:", warn_codes)
        except NoResultsError as e:
            print("  status=NO_RESULTS")
            print("  error_message:", str(e))
            if soap_dumper is not None:
                soap_dumper.dump(f"HotelAvail-NO_RESULTS-{city_name}-{zone_code}")
        except JuniperFaultError as e:
            all_ok = False
            print("  status=FAILED")
            print("  error_code:", e.fault_code)
            print("  error_message:", e.fault_string)
            if soap_dumper is not None:
                soap_dumper.dump(f"HotelAvail-FAULT-{city_name}-{zone_code}")
        except Exception as e:
            all_ok = False
            print("  status=FAILED")
            print("  error_type:", type(e).__name__)
            print("  error_message:", str(e))
            if soap_dumper is not None:
                soap_dumper.dump(f"HotelAvail-ERROR-{city_name}-{zone_code}")

        # Full-booking chain — only when the caller asked for it AND we
        # actually got a bookable option from HotelAvail. Intentionally
        # runs per-city so a green Palma doesn't get blocked by an empty
        # Dubai result.
        if (full_booking or confirm_booking) and picked_row is not None:
            try:
                ok = await _run_full_booking_chain(
                    client,
                    picked_row,
                    city_name=city_name,
                    zone_code=zone_code,
                    check_in=ci,
                    check_out=co,
                    country=country,
                    adults=adults,
                    children=children,
                    confirm_booking=confirm_booking,
                    soap_dumper=soap_dumper,
                    persist_db=persist_db,
                    sandbox_external_user_id=sandbox_external_user_id,
                )
                if not ok:
                    all_ok = False
            except Exception as exc:  # noqa: BLE001
                all_ok = False
                print("  [full-booking] UNCAUGHT ERROR:", type(exc).__name__, "—", exc)
        elif (full_booking or confirm_booking) and picked_row is None:
            # Not fatal: we still got through HotelAvail cleanly, and the
            # next city may have stock.
            print("  [full-booking] skipped: no OK HotelOption in this city's HotelAvail result")

    return 0 if all_ok else 1


async def _run_legacy_mode(client: JuniperClient) -> int:
    """Reproduce the ticket-1096690 REQ_PRACTICE bug for support evidence."""
    ci = (date.today() + timedelta(days=45)).isoformat()
    co = (date.today() + timedelta(days=48)).isoformat()
    all_ok = True

    print("\n--- HotelAvail dual-city (LEGACY DestinationZone — expected to FAIL) ---")
    for city_name, zone_code in TEST_ZONES:
        print(f"\n[HotelAvail] city={city_name}, zone={zone_code}  (expecting REQ_PRACTICE)")
        try:
            # zone_code path is intentionally ignored by the real client now;
            # this just proves the behaviour end-to-end with no hotel_codes.
            hotels = await client.hotel_avail(
                zone_code=zone_code,
                check_in=ci, check_out=co,
                adults=2, children=0,
                country_of_residence="ES",
            )
            print(f"  status=OK, hotels={len(hotels)}  (unexpected — supplier may have lifted the policy)")
        except ValueError as e:
            # New client validates hotel_codes is present — documents the migration.
            print("  status=CLIENT_REJECTED (post-migration validation)")
            print("  message:", str(e))
        except JuniperFaultError as e:
            all_ok = False
            print("  status=FAILED  (expected REQ_PRACTICE)")
            print("  error_code:", e.fault_code)
            print("  error_message:", e.fault_string)
        except Exception as e:
            all_ok = False
            print("  status=FAILED")
            print("  error_type:", type(e).__name__)
            print("  error_message:", str(e))

    return 0 if all_ok else 1


async def _run(
    mode: str,
    *,
    codes_per_zone: int,
    use_known_good: bool,
    debug_soap: bool,
    full_booking: bool = False,
    confirm_booking: bool = False,
    persist_db: bool = False,
    sandbox_external_user_id: str = "sandbox-uat-persist",
) -> int:
    if settings.juniper_use_mock:
        print("Set JUNIPER_USE_MOCK=false in .env to hit real xml-uat SOAP.", file=sys.stderr)
        return 2
    if not settings.juniper_email or not settings.juniper_password:
        print("Set JUNIPER_EMAIL and JUNIPER_PASSWORD in .env.", file=sys.stderr)
        return 2

    print("JUNIPER_API_URL:", settings.juniper_api_url)
    print("JUNIPER_EMAIL:", settings.juniper_email)
    print("JUNIPER_PASSWORD(masked):", _mask_password(settings.juniper_password))
    print("WSDL:", f"{settings.juniper_api_url.rstrip('/')}/webservice/JP/WebServiceJP.asmx?WSDL")
    print("MODE:", mode)

    client = JuniperClient()

    soap_dumper: _SoapDumper | None = None
    if debug_soap:
        soap_dumper = _SoapDumper(client, _ROOT / "logs" / "soap_dumps")
        print(f"DEBUG_SOAP: dumping last request/response XML under {soap_dumper._out_dir}")  # noqa: SLF001

    print("\n--- ZoneList (ProductType=HOT) ---")
    try:
        zones = await client.zone_list(product_type="HOT")
    except Exception as e:
        print("ZoneList FAILED:", repr(e))
        return 1
    print(f"OK: {len(zones)} zones (showing first 3 names)")
    for z in zones[:3]:
        print(" ", z.get("name"), "|", z.get("code"), "| jpdcode=", z.get("jpdcode"))

    if mode == "legacy":
        if full_booking or confirm_booking:
            print(
                "NOTE: --full-booking / --confirm-booking are ignored in "
                "legacy mode (HotelAvail expected to fail with REQ_PRACTICE).",
                file=sys.stderr,
            )
        return await _run_legacy_mode(client)
    return await _run_hotelcodes_mode(
        client,
        codes_per_zone=codes_per_zone,
        use_known_good=use_known_good,
        full_booking=full_booking or confirm_booking,
        confirm_booking=confirm_booking,
        soap_dumper=soap_dumper,
        persist_db=persist_db,
        sandbox_external_user_id=sandbox_external_user_id,
    )


def _parse_args() -> argparse.Namespace:
    p = argparse.ArgumentParser(description="Juniper UAT SOAP sandbox smoke test.")
    p.add_argument(
        "--mode",
        choices=["hotelcodes", "legacy"],
        default="hotelcodes",
        help="hotelcodes (default): post-ticket-1096690 path; "
             "legacy: old DestinationZone path (expected to fail).",
    )
    p.add_argument(
        "--codes-per-zone",
        type=int,
        default=SANDBOX_CODES_PER_ZONE,
        metavar="N",
        help=f"JPCodes per city (default {SANDBOX_CODES_PER_ZONE}). "
             "Raise to hit more UAT inventory when the default 5 all return NO_AVAIL_FOUND.",
    )
    p.add_argument(
        "--use-known-good",
        action="store_true",
        help="Prepend Juniper-confirmed JPCodes (e.g. JP046300 for Palma 15011) "
             "before cache codes. Use to prove the full chain returns OK when UAT "
             "inventory for the top-N cache codes is thin.",
    )
    p.add_argument(
        "--debug-soap",
        action="store_true",
        help="Attach zeep HistoryPlugin and dump the last SOAP request+response "
             "XML under ``logs/soap_dumps/`` for each HotelAvail call. Use when "
             "diagnosing NO_RESULTS vs. serializer-drops-valid-inventory.",
    )
    p.add_argument(
        "--full-booking",
        action="store_true",
        help="After HotelAvail, run HotelCheckAvail + HotelBookingRules "
             "against the cheapest OK option's RatePlanCode. Both calls are "
             "idempotent / read-only — no reservation is committed.",
    )
    p.add_argument(
        "--confirm-booking",
        action="store_true",
        help="Implies --full-booking AND calls HotelBooking, creating a real "
             "reservation in Juniper's UAT with a synthetic test guest "
             "(sandbox-<uuid>@juniperai.test). The locator is printed so the "
             "reservation can be cancelled later via CancelBooking.",
    )
    p.add_argument(
        "--persist-db",
        action="store_true",
        help="After a successful HotelBooking, insert into PostgreSQL bookings "
             "(requires DATABASE_URL and --confirm-booking). Creates stub "
             "users + conversations rows; see --sandbox-external-user-id.",
    )
    p.add_argument(
        "--sandbox-external-user-id",
        default="sandbox-uat-persist",
        metavar="EXT_ID",
        help="External user id for the stub users row when using --persist-db "
             "(default: sandbox-uat-persist).",
    )
    return p.parse_args()


def main() -> None:
    args = _parse_args()
    if args.persist_db and not args.confirm_booking:
        print("--persist-db requires --confirm-booking", file=sys.stderr)
        raise SystemExit(2)
    raise SystemExit(asyncio.run(_run(
        args.mode,
        codes_per_zone=args.codes_per_zone,
        use_known_good=args.use_known_good,
        debug_soap=args.debug_soap,
        full_booking=args.full_booking,
        confirm_booking=args.confirm_booking,
        persist_db=args.persist_db,
        sandbox_external_user_id=args.sandbox_external_user_id,
    )))


if __name__ == "__main__":
    main()
