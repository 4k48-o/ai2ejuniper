"""Read-only Agent tools backed by local PostgreSQL static cache (L1/L2).

No SOAP calls. Use for destination disambiguation, listing cached hotels by zone
tree, and decoding catalogue codes. Inventory and prices still require
search_hotels / check_availability / get_booking_rules (Juniper).
"""

from __future__ import annotations

import json
import logging
import re

from langchain_core.tools import tool

from juniper_ai.app.db.session import async_session
from juniper_ai.app.juniper import static_data as static_data_layer

logger = logging.getLogger(__name__)

_JPD_SPLIT = re.compile(r"[\s,;]+")


def _parse_jpdcode_list(zone_jpdcodes: str) -> list[str]:
    s = (zone_jpdcodes or "").strip()
    if not s:
        return []
    return [p for p in _JPD_SPLIT.split(s) if p]


@tool
async def resolve_destination(destination_text: str, max_candidates: int = 8) -> str:
    """Resolve a free-text destination to Juniper zone(s) using ONLY the local zones table.

    Use BEFORE or INSTEAD OF guessing zone codes. Does not call Juniper.

    Args:
        destination_text: User phrase (e.g. city or region name).
        max_candidates: Max rows when status is ambiguous (default 8).

    Returns:
        JSON with keys: status (unique|ambiguous|none), query, best, candidates, hint.
    """
    logger.info("Tool resolve_destination: %s", destination_text)
    lim = max(1, min(int(max_candidates or 8), 24))
    async with async_session() as db:
        payload = await static_data_layer.resolve_destination(db, destination_text, limit=lim)
    return json.dumps(payload, ensure_ascii=False)


@tool
async def list_hotels_for_zones(
    zone_jpdcodes: str,
    limit: int = 30,
    offset: int = 0,
    expand_descendants: bool = True,
) -> str:
    """List hotels from local `hotel_cache` for one or more zone JPDCode values.

    When expand_descendants is true (default), includes hotels mapped to child zones
    (PostgreSQL recursive query on `zones`). Does NOT check live availability or prices.

    Args:
        zone_jpdcodes: One or more JPDCode values separated by comma/space/semicolon
            (e.g. "JPD081673" or "JPD081673, JPD088282").
        limit: Max hotels to return (1–200, default 30).
        offset: Pagination offset (default 0).
        expand_descendants: If true, include hotels in descendant zones (default true).

    Returns:
        JSON with hotels (jp_code, name, zone_jpdcode, category_type, city_name),
        has_more, zone_jpdcodes_resolved, offset, limit.
    """
    logger.info("Tool list_hotels_for_zones: jpdcodes=%s limit=%s offset=%s", zone_jpdcodes, limit, offset)
    jpds = _parse_jpdcode_list(zone_jpdcodes)
    if not jpds:
        return json.dumps(
            {"error": "No zone_jpdcodes provided.", "hotels": [], "has_more": False},
            ensure_ascii=False,
        )
    lim = int(limit) if limit is not None else 30
    off = int(offset) if offset is not None else 0
    exp = bool(expand_descendants) if expand_descendants is not None else True
    async with async_session() as db:
        payload = await static_data_layer.list_hotels_in_zone_jpdcodes(
            db, jpds, limit=lim, offset=off, expand_descendants=exp,
        )
    return json.dumps(payload, ensure_ascii=False)


@tool
async def explain_catalog(code_type: str, code: str) -> str:
    """Decode a catalogue code from local static tables (board / star category / country / currency).

    code_type accepts (case-insensitive):
        board | hotel_category | country | currency
    (aliases: board_type, category, country_iso, curr).

    Args:
        code_type: Which table to query.
        code: Supplier code (e.g. AD, 5est, ES, EUR).

    Returns:
        JSON with code_type, code, name — or {\"found\": false} if unknown.
    """
    logger.info("Tool explain_catalog: type=%s code=%s", code_type, code)
    async with async_session() as db:
        row = await static_data_layer.explain_catalog_lookup(db, code_type, code)
    if not row:
        return json.dumps({"found": False, "code_type": code_type, "code": code}, ensure_ascii=False)
    return json.dumps({"found": True, **row}, ensure_ascii=False)
