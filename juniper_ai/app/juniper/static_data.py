"""Static data service — sync Juniper catalogues to local DB and provide lookups."""

import logging
from datetime import datetime, timezone

from sqlalchemy import select, delete
from sqlalchemy.dialects.postgresql import insert as pg_insert
from sqlalchemy.ext.asyncio import AsyncSession

from juniper_ai.app.db.models import (
    BoardType,
    Country,
    Currency,
    HotelCache,
    HotelCategory,
    HotelContentCache,
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


async def get_zone_code(db: AsyncSession, destination_text: str) -> dict | None:
    """Fuzzy-match a destination text to a zone code.

    Tries exact match first, then ILIKE. Returns the best searchable match
    as {"jpdcode": ..., "code": ..., "name": ..., "area_type": ...} or None.
    """
    text = destination_text.strip()

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
    text = destination_text.strip()
    result = await db.execute(
        select(Zone).where(
            Zone.name.ilike(f"%{text}%"),
            Zone.searchable.is_(True),
        ).order_by(Zone.area_type)
        .limit(limit)
    )
    return [
        {"jpdcode": z.jpdcode, "code": z.code, "name": z.name, "area_type": z.area_type}
        for z in result.scalars().all()
    ]


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
