#!/usr/bin/env python3
"""Smoke-test Juniper xml-uat SOAP (Flicknmix credentials).

Two modes:
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
from datetime import date, timedelta
from pathlib import Path

_ROOT = Path(__file__).resolve().parents[1]
if str(_ROOT) not in sys.path:
    sys.path.insert(0, str(_ROOT))

from sqlalchemy import select

from juniper_ai.app.config import settings
from juniper_ai.app.db.models import Zone
from juniper_ai.app.db.session import async_session
from juniper_ai.app.juniper.client import JuniperClient
from juniper_ai.app.juniper.exceptions import JuniperFaultError, NoResultsError
from juniper_ai.app.juniper.static_data import list_hotels_in_zone_jpdcodes


TEST_ZONES = [
    ("Palma de Mallorca", "15011"),
    ("Dubai City", "13826"),
]

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


async def _resolve_jpcodes_for_zone(zone_code: str) -> tuple[str, list[str], str]:
    """Return (jpdcode, jpcodes, source). ``source`` is ``cache`` or ``fallback``."""
    async with async_session() as db:
        row = await db.execute(
            select(Zone).where(Zone.code == zone_code).limit(1)
        )
        zone = row.scalar_one_or_none()
        if not zone:
            return ("", KNOWN_GOOD_JPCODES.get(zone_code, []), "fallback-no-zone")

        codes = await list_hotels_in_zone_jpdcodes(
            db, [zone.jpdcode],
            limit=SANDBOX_CODES_PER_ZONE,
            expand_descendants=True,
            only_jpcodes=True,
        )
        if codes:
            return (zone.jpdcode, list(codes), "cache")
        # DB knows the zone but no hotels cached — fall back if we have a seed.
        return (zone.jpdcode, KNOWN_GOOD_JPCODES.get(zone_code, []), "fallback-empty-cache")


async def _run_hotelcodes_mode(client: JuniperClient) -> int:
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
            "codes_per_zone_cap": SANDBOX_CODES_PER_ZONE,
        },
    )

    for city_name, zone_code in TEST_ZONES:
        jpdcode, jpcodes, source = await _resolve_jpcodes_for_zone(zone_code)
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

        try:
            hotels = await client.hotel_avail(
                hotel_codes=jpcodes,
                check_in=ci, check_out=co,
                adults=adults, children=children,
                country_of_residence=country,
            )
            print(f"  status=OK, hotels={len(hotels)}")
            for h in hotels[:2]:
                print("   ", h.get("name"), "|", h.get("total_price"), h.get("currency"))
        except NoResultsError as e:
            print("  status=NO_RESULTS")
            print("  error_message:", str(e))
        except JuniperFaultError as e:
            all_ok = False
            print("  status=FAILED")
            print("  error_code:", e.fault_code)
            print("  error_message:", e.fault_string)
        except Exception as e:
            all_ok = False
            print("  status=FAILED")
            print("  error_type:", type(e).__name__)
            print("  error_message:", str(e))

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


async def _run(mode: str) -> int:
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
        return await _run_legacy_mode(client)
    return await _run_hotelcodes_mode(client)


def _parse_args() -> argparse.Namespace:
    p = argparse.ArgumentParser(description="Juniper UAT SOAP sandbox smoke test.")
    p.add_argument(
        "--mode",
        choices=["hotelcodes", "legacy"],
        default="hotelcodes",
        help="hotelcodes (default): post-ticket-1096690 path; "
             "legacy: old DestinationZone path (expected to fail).",
    )
    return p.parse_args()


def main() -> None:
    args = _parse_args()
    raise SystemExit(asyncio.run(_run(args.mode)))


if __name__ == "__main__":
    main()
