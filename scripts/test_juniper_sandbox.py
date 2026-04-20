#!/usr/bin/env python3
"""Smoke-test Juniper xml-uat SOAP (Flicknmix credentials).

Prerequisites:
  - `.env` with JUNIPER_USE_MOCK=false, JUNIPER_API_URL, JUNIPER_EMAIL, JUNIPER_PASSWORD
  - Run from repo root:  python scripts/test_juniper_sandbox.py

Supplier test zones (DestinationZone / zone code for HotelAvail):
  - Palma de Mallorca: 15011
  - Dubai City: 13826
"""

from __future__ import annotations

import asyncio
import sys
from datetime import date, timedelta
from pathlib import Path

# Repo root on path
_ROOT = Path(__file__).resolve().parents[1]
if str(_ROOT) not in sys.path:
    sys.path.insert(0, str(_ROOT))

from juniper_ai.app.config import settings
from juniper_ai.app.juniper.client import JuniperClient
from juniper_ai.app.juniper.exceptions import JuniperFaultError


TEST_ZONES = [
    ("Palma de Mallorca", "15011"),
    ("Dubai City", "13826"),
]


def _mask_password(raw: str) -> str:
    if not raw:
        return ""
    if len(raw) <= 4:
        return "*" * len(raw)
    return f"{raw[:2]}***{raw[-2:]}"


async def _run() -> int:
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

    ci = (date.today() + timedelta(days=45)).isoformat()
    co = (date.today() + timedelta(days=48)).isoformat()
    adults = 2
    children = 0
    country = "ES"
    all_ok = True

    print("\n--- HotelAvail dual-city check ---")
    print(
        "Request summary:",
        {
            "check_in": ci,
            "check_out": co,
            "adults": adults,
            "children": children,
            "country_of_residence": country,
            "zones": [{"name": name, "code": code} for name, code in TEST_ZONES],
        },
    )
    for city_name, zone_code in TEST_ZONES:
        print(f"\n[HotelAvail] city={city_name}, zone={zone_code}")
        try:
            hotels = await client.hotel_avail(
                zone_code=zone_code,
                check_in=ci,
                check_out=co,
                adults=adults,
                children=children,
                country_of_residence=country,
            )
            print(f"  status=OK, hotels={len(hotels)}")
            for h in hotels[:2]:
                print("   ", h.get("name"), "|", h.get("total_price"), h.get("currency"))
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

    if not all_ok:
        print("\nSandbox SOAP checks finished with failures.")
        return 1

    print("\nSandbox SOAP checks passed.")
    return 0


def main() -> None:
    raise SystemExit(asyncio.run(_run()))


if __name__ == "__main__":
    main()
