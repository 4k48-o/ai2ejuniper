"""Background task to sync Juniper static data to local database."""

import logging

from juniper_ai.app.config import settings
from juniper_ai.app.db.session import async_session
from juniper_ai.app.juniper.mock_client import get_juniper_client
from juniper_ai.app.juniper.static_data import sync_catalogue, sync_hotels, sync_zones

logger = logging.getLogger(__name__)


async def run_full_sync() -> dict:
    """Execute a full static data synchronization.

    Syncs zones, hotel portfolio, and catalogues (currencies, countries,
    hotel categories, board types). Should be run on first startup and
    then periodically (every ~15 days per Juniper certification requirement).

    Returns a summary dict with counts.
    """
    client = get_juniper_client()
    summary = {}

    async with async_session() as db:
        try:
            zone_count = await sync_zones(client, db)
            summary["zones"] = zone_count

            hotel_count = await sync_hotels(client, db, page_size=settings.hotel_portfolio_page_size)
            summary["hotels"] = hotel_count

            catalogue_counts = await sync_catalogue(client, db)
            summary.update(catalogue_counts)

            await db.commit()
            logger.info("Full static data sync completed: %s", summary)
        except Exception:
            await db.rollback()
            logger.error("Static data sync failed", exc_info=True)
            raise

    return summary
