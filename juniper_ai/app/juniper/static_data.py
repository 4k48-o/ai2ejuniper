"""Static data service — sync Juniper catalogues to local DB and provide lookups."""

import logging
from datetime import datetime, timezone

from sqlalchemy import select, bindparam, text
from sqlalchemy.dialects.postgresql import insert as pg_insert
from sqlalchemy.ext.asyncio import AsyncSession

from juniper_ai.app.db.models import (
    BoardType,
    Country,
    Currency,
    HotelCache,
    HotelCategory,
    Zone,
)
from juniper_ai.app.juniper.supplier import HotelSupplier

logger = logging.getLogger(__name__)


async def sync_zones(client: HotelSupplier, db: AsyncSession) -> int:
    """Sync destination zones from ZoneList API into the zones table.

    Returns the number of zones synced.
    """
    logger.info("Syncing zones...")
    zones = await client.zone_list(product_type="HOT")
    now = datetime.now(timezone.utc)

    for z in zones:
        stmt = pg_insert(Zone.__table__).values(
            jpdcode=z["jpdcode"],
            code=z["code"],
            name=z["name"],
            area_type=z.get("area_type", ""),
            searchable=z.get("searchable", True),
            parent_jpdcode=z.get("parent_jpdcode", ""),
            synced_at=now,
        ).on_conflict_do_update(
            index_elements=["jpdcode"],
            set_={"code": z["code"], "name": z["name"], "area_type": z.get("area_type", ""),
                   "searchable": z.get("searchable", True), "parent_jpdcode": z.get("parent_jpdcode", ""),
                   "synced_at": now},
        )
        await db.execute(stmt)

    await db.flush()
    logger.info("Synced %d zones", len(zones))
    return len(zones)


async def sync_hotels(client: HotelSupplier, db: AsyncSession, page_size: int = 500) -> int:
    """Sync hotel portfolio from HotelPortfolio API (paginated).

    Returns the total number of hotels synced.
    """
    logger.info("Syncing hotel portfolio (page_size=%d)...", page_size)
    now = datetime.now(timezone.utc)
    total = 0
    page_token = None

    while True:
        result = await client.hotel_portfolio(page_token=page_token, page_size=page_size)
        hotels = result.get("hotels", [])

        for h in hotels:
            stmt = pg_insert(HotelCache.__table__).values(
                jp_code=h["jp_code"],
                name=h["name"],
                zone_jpdcode=h.get("zone_jpdcode", ""),
                category_type=h.get("category_type", ""),
                address=h.get("address", ""),
                latitude=h.get("latitude", ""),
                longitude=h.get("longitude", ""),
                city_name=h.get("city_name", ""),
                city_jpdcode=h.get("city_jpdcode", ""),
                synced_at=now,
            ).on_conflict_do_update(
                index_elements=["jp_code"],
                set_={"name": h["name"], "zone_jpdcode": h.get("zone_jpdcode", ""),
                       "category_type": h.get("category_type", ""), "address": h.get("address", ""),
                       "latitude": h.get("latitude", ""), "longitude": h.get("longitude", ""),
                       "city_name": h.get("city_name", ""), "city_jpdcode": h.get("city_jpdcode", ""),
                       "synced_at": now},
            )
            await db.execute(stmt)

        total += len(hotels)
        await db.flush()

        page_token = result.get("next_token", "")
        if not page_token:
            break
        logger.info("Synced %d hotels so far, fetching next page...", total)

    logger.info("Synced %d hotels total", total)
    return total


async def sync_catalogue(client: HotelSupplier, db: AsyncSession) -> dict:
    """Sync currencies, countries, hotel categories, and board types.

    Returns counts per type.
    """
    logger.info("Syncing catalogues...")
    now = datetime.now(timezone.utc)
    counts = {}

    # Currencies
    currencies = await client.generic_data_catalogue("CURRENCY")
    for c in currencies:
        stmt = pg_insert(Currency.__table__).values(
            code=c["code"], name=c["name"], synced_at=now,
        ).on_conflict_do_update(index_elements=["code"], set_={"name": c["name"], "synced_at": now})
        await db.execute(stmt)
    counts["currencies"] = len(currencies)

    # Countries
    countries = await client.generic_data_catalogue("COUNTRIES")
    for c in countries:
        stmt = pg_insert(Country.__table__).values(
            code=c["code"], name=c["name"], synced_at=now,
        ).on_conflict_do_update(index_elements=["code"], set_={"name": c["name"], "synced_at": now})
        await db.execute(stmt)
    counts["countries"] = len(countries)

    # Hotel-specific catalogues
    catalogue = await client.hotel_catalogue_data()

    for cat in catalogue.get("hotel_categories", []):
        stmt = pg_insert(HotelCategory.__table__).values(
            type=cat["code"], name=cat["name"], synced_at=now,
        ).on_conflict_do_update(index_elements=["type"], set_={"name": cat["name"], "synced_at": now})
        await db.execute(stmt)
    counts["hotel_categories"] = len(catalogue.get("hotel_categories", []))

    for bt in catalogue.get("board_types", []):
        stmt = pg_insert(BoardType.__table__).values(
            code=bt["code"], name=bt["name"], synced_at=now,
        ).on_conflict_do_update(index_elements=["code"], set_={"name": bt["name"], "synced_at": now})
        await db.execute(stmt)
    counts["board_types"] = len(catalogue.get("board_types", []))

    await db.flush()
    logger.info("Synced catalogues: %s", counts)
    return counts


# ---------------------------------------------------------------------------
# Lookup helpers
# ---------------------------------------------------------------------------


# Short user inputs that collide with multiple supplier ``Zone`` rows (same
# ``name`` in different countries). Map → canonical searchable name we want
# for hotel search (see get_zone_code).
_ZONE_SHORT_NAME_ALIASES: dict[str, str] = {
    # "Palma" alone matches several CTY; Mallorca is the usual travel intent + JP046300 smoke.
    "palma": "Palma de Mallorca",
}


async def get_zone_code(db: AsyncSession, destination_text: str) -> dict | None:
    """Fuzzy-match a destination text to a zone code.

    Tries short-name aliases (homonyms), exact match, then contains ILIKE.
    Returns the best searchable match
    as {"jpdcode": ..., "code": ..., "name": ..., "area_type": ...} or None.
    """
    text = destination_text.strip()

    alias_name = _ZONE_SHORT_NAME_ALIASES.get(text.lower())
    if alias_name:
        result = await db.execute(
            select(Zone).where(
                Zone.name.ilike(alias_name),
                Zone.searchable.is_(True),
            ).limit(1)
        )
        zone = result.scalar_one_or_none()
        if zone:
            return {"jpdcode": zone.jpdcode, "code": zone.code, "name": zone.name, "area_type": zone.area_type}

    # 1. Exact match (case-insensitive)
    result = await db.execute(
        select(Zone).where(
            Zone.name.ilike(text),
            Zone.searchable.is_(True),
        ).limit(1)
    )
    zone = result.scalar_one_or_none()
    if zone:
        return {"jpdcode": zone.jpdcode, "code": zone.code, "name": zone.name, "area_type": zone.area_type}

    # 2. Contains match
    result = await db.execute(
        select(Zone).where(
            Zone.name.ilike(f"%{text}%"),
            Zone.searchable.is_(True),
        ).order_by(Zone.area_type)  # Prefer CTY over REG/PAS
        .limit(5)
    )
    zones = result.scalars().all()
    if zones:
        # Prefer city-level matches
        for z in zones:
            if z.area_type == "CTY":
                return {"jpdcode": z.jpdcode, "code": z.code, "name": z.name, "area_type": z.area_type}
        z = zones[0]
        return {"jpdcode": z.jpdcode, "code": z.code, "name": z.name, "area_type": z.area_type}

    return None


async def get_zone_candidates(db: AsyncSession, destination_text: str, limit: int = 10) -> list[dict]:
    """Return multiple zone matches for disambiguation."""
    raw = destination_text.strip()
    result = await db.execute(
        select(Zone).where(
            Zone.name.ilike(f"%{raw}%"),
            Zone.searchable.is_(True),
        ).order_by(Zone.area_type)
        .limit(limit)
    )
    return [
        {"jpdcode": z.jpdcode, "code": z.code, "name": z.name, "area_type": z.area_type}
        for z in result.scalars().all()
    ]


def _area_type_sort_key(area_type: str | None) -> tuple[int, str]:
    """Prefer city-level zones, then stable name ordering for disambiguation."""
    rank = {"CTY": 0, "BAR": 1, "REG": 2, "PAS": 3, "CTI": 4}
    at = (area_type or "").strip().upper()
    return (rank.get(at, 9), at)


async def resolve_destination(db: AsyncSession, destination_text: str, limit: int = 8) -> dict:
    """Structured destination resolution for Agent tools (DB only).

    Returns:
        status: "unique" | "ambiguous" | "none"
        best: single zone dict or None
        candidates: sorted list of {jpdcode, code, name, area_type, hint}
    """
    raw = (destination_text or "").strip()
    if not raw:
        return {"status": "none", "query": raw, "best": None, "candidates": [], "hint": "Empty destination text."}

    best = await get_zone_code(db, raw)
    if best:
        cand = {**best, "hint": "Use this zone's `code` as destination zone for search_hotels (SOAP)."}
        return {"status": "unique", "query": raw, "best": best, "candidates": [cand], "hint": None}

    raw_list = await get_zone_candidates(db, raw, limit=max(limit * 3, 24))
    if not raw_list:
        return {
            "status": "none",
            "query": raw,
            "best": None,
            "candidates": [],
            "hint": "No searchable zones matched. Try another spelling or broader region name.",
        }

    scored = sorted(
        raw_list,
        key=lambda z: (_area_type_sort_key(z.get("area_type")), len(z.get("name", "")), z.get("name", "")),
    )[:limit]

    candidates = []
    for z in scored:
        hint = (
            f"Area type {z.get('area_type', '')}; jpdcode={z.get('jpdcode', '')}. "
            "If multiple rows, ask the user which city/area they mean before searching."
        )
        candidates.append({**z, "hint": hint})

    return {
        "status": "ambiguous",
        "query": raw,
        "best": None,
        "candidates": candidates,
        "hint": "Ask the user to pick one zone (by name) or refine the destination, then call search_hotels.",
    }


async def expand_zone_jpdcodes(db: AsyncSession, root_jpdcodes: list[str]) -> list[str]:
    """All zone `jpdcode` values that are roots or descendants (children) of roots.

    Uses PostgreSQL `WITH RECURSIVE`. Empty / duplicate roots are ignored.
    """
    roots = list(dict.fromkeys(r.strip() for r in root_jpdcodes if r and str(r).strip()))
    if not roots:
        return []

    stmt = (
        text(
            """
            WITH RECURSIVE subzones AS (
                SELECT jpdcode FROM zones WHERE jpdcode IN :roots
                UNION ALL
                SELECT z.jpdcode FROM zones z
                INNER JOIN subzones s ON z.parent_jpdcode = s.jpdcode
                  AND COALESCE(NULLIF(TRIM(z.parent_jpdcode), ''), '') <> ''
            )
            SELECT DISTINCT jpdcode FROM subzones
            """
        ).bindparams(bindparam("roots", expanding=True))
    )
    result = await db.execute(stmt, {"roots": tuple(roots)})
    return [row[0] for row in result.fetchall()]


async def list_hotels_in_zone_jpdcodes(
    db: AsyncSession,
    jpdcode_list: list[str],
    *,
    limit: int = 30,
    offset: int = 0,
    expand_descendants: bool = True,
    only_jpcodes: bool = False,
) -> dict | list[str]:
    """List hotels from ``hotel_cache`` whose ``zone_jpdcode`` falls under the given zone(s).

    When ``expand_descendants`` is True, includes hotels in child zones
    (PostgreSQL recursive CTE via :func:`expand_zone_jpdcodes`).

    Two call modes:

    * **Default (``only_jpcodes=False``)** — used by the agent's LLM-facing
      tool :func:`juniper_ai.app.agent.tools.static_lookup_tools.list_hotels_for_zones`.
      Returns the full paginated dict with ``hotels`` (each including
      ``name``, ``city_name``, ``category_type`` …), ``has_more``, etc.
      Intended for LLM display, so callers see human-readable context.

    * **Fast path (``only_jpcodes=True``)** — used by the internal
      :func:`juniper_ai.app.agent.tools.search_hotels.search_hotels` flow.
      SELECTs only the ``jp_code`` column (no ORM hydration) and returns
      a deduplicated ``list[str]``. Optimized for feeding Juniper
      ``HotelAvail`` via ``HotelCodes``. ``offset`` is still honoured,
      but pagination metadata is dropped — search_hotels just wants the
      code list up to ``limit``.

    Returns:
        ``dict`` (default) or ``list[str]`` (``only_jpcodes=True``).
    """
    lim = max(1, min(limit, 200))
    off = max(0, offset)

    if expand_descendants:
        zone_keys = await expand_zone_jpdcodes(db, jpdcode_list)
    else:
        zone_keys = list(dict.fromkeys(j.strip() for j in jpdcode_list if j and j.strip()))

    if not zone_keys:
        if only_jpcodes:
            return []
        return {
            "hotels": [],
            "total_returned": 0,
            "has_more": False,
            "zone_jpdcodes_resolved": [],
            "offset": off,
            "limit": lim,
        }

    if only_jpcodes:
        # Fast path: select only the code column, no ORM hydration.
        # The LIKE 'JP%' guard filters out any non-Juniper codes (e.g. mock
        # fixtures accidentally seeded with JUNIPER_USE_MOCK=true); Juniper's
        # JPCode is globally prefixed "JP" by definition (see
        # doc/juniper-hotel-api.md §Hotel Generic Types).
        q = (
            select(HotelCache.jp_code)
            .where(HotelCache.zone_jpdcode.in_(zone_keys))
            .where(HotelCache.jp_code.isnot(None))
            .where(HotelCache.jp_code.like("JP%"))
            .order_by(HotelCache.jp_code)
            .offset(off)
            .limit(lim)
        )
        result = await db.execute(q)
        return [row[0] for row in result.all() if row[0]]

    q = (
        select(HotelCache)
        .where(HotelCache.zone_jpdcode.in_(zone_keys))
        .order_by(HotelCache.jp_code)
        .offset(off)
        .limit(lim + 1)
    )
    result = await db.execute(q)
    rows = list(result.scalars().all())
    has_more = len(rows) > lim
    rows = rows[:lim]

    hotels = [
        {
            "jp_code": h.jp_code,
            "name": h.name,
            "zone_jpdcode": h.zone_jpdcode or "",
            "category_type": h.category_type or "",
            "city_name": h.city_name or "",
        }
        for h in rows
    ]
    return {
        "hotels": hotels,
        "total_returned": len(hotels),
        "has_more": has_more,
        "zone_jpdcodes_resolved": zone_keys,
        "offset": off,
        "limit": lim,
    }


async def explain_catalog_lookup(db: AsyncSession, code_type: str, code: str) -> dict | None:
    """Return display name for a catalogue code (DB only). code_type: board|hotel_category|country|currency"""
    ct = (code_type or "").lower().strip()
    c = (code or "").strip()
    if not c:
        return None

    if ct in ("board", "board_type", "meal", "meal_plan"):
        row = await db.get(BoardType, c)
        if row:
            return {"code_type": "board", "code": row.code, "name": row.name}
    elif ct in ("hotel_category", "category", "star", "stars"):
        row = await db.get(HotelCategory, c)
        if row:
            return {"code_type": "hotel_category", "code": row.type, "name": row.name}
    elif ct in ("country", "country_iso"):
        row = await db.get(Country, c.upper())
        if row:
            return {"code_type": "country", "code": row.code, "name": row.name}
    elif ct in ("currency", "curr"):
        row = await db.get(Currency, c.upper())
        if row:
            return {"code_type": "currency", "code": row.code, "name": row.name}
    return None


async def get_hotel_by_jpcode(db: AsyncSession, jp_code: str) -> dict | None:
    """Lookup a hotel from the local cache by JPCode."""
    result = await db.execute(
        select(HotelCache).where(HotelCache.jp_code == jp_code)
    )
    h = result.scalar_one_or_none()
    if not h:
        return None
    return {
        "jp_code": h.jp_code, "name": h.name, "zone_jpdcode": h.zone_jpdcode,
        "category_type": h.category_type, "address": h.address,
        "latitude": h.latitude, "longitude": h.longitude,
    }
