"""Tests for static data sync and zone code lookup."""

import pytest
from unittest.mock import AsyncMock, MagicMock, patch

from juniper_ai.app.juniper.static_data import (
    expand_zone_jpdcodes,
    explain_catalog_lookup,
    get_zone_code,
    get_zone_candidates,
    list_hotels_in_zone_jpdcodes,
    resolve_destination,
    sync_catalogue,
    sync_hotels,
    sync_zones,
)


class _FakeAsyncSessionCM:
    def __init__(self, db):
        self._db = db

    async def __aenter__(self):
        return self._db

    async def __aexit__(self, *args):
        return False


# ---------------------------------------------------------------------------
# sync_zones
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_sync_zones_inserts_records():
    """Zones from supplier are upserted into zones table."""
    mock_client = AsyncMock()
    mock_client.zone_list.return_value = [
        {"jpdcode": "JPD001", "code": "100", "name": "Barcelona", "area_type": "CTY", "searchable": True, "parent_jpdcode": "JPD000"},
        {"jpdcode": "JPD000", "code": "1", "name": "Spain", "area_type": "PAS", "searchable": True, "parent_jpdcode": ""},
    ]

    mock_db = AsyncMock()
    mock_db.execute = AsyncMock()
    mock_db.flush = AsyncMock()

    count = await sync_zones(mock_client, mock_db)

    assert count == 2
    mock_client.zone_list.assert_awaited_once_with(product_type="HOT")
    assert mock_db.execute.await_count == 2
    mock_db.flush.assert_awaited_once()


# ---------------------------------------------------------------------------
# sync_hotels
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_sync_hotels_paginates():
    """Hotels are fetched page by page until next_token is empty."""
    mock_client = AsyncMock()
    mock_client.hotel_portfolio.side_effect = [
        {"hotels": [{"jp_code": f"JP{i}", "name": f"Hotel {i}", "zone_jpdcode": "", "category_type": "", "address": "", "latitude": "", "longitude": "", "city_name": "", "city_jpdcode": ""} for i in range(3)], "next_token": "page2", "total_records": 5},
        {"hotels": [{"jp_code": f"JP{i}", "name": f"Hotel {i}", "zone_jpdcode": "", "category_type": "", "address": "", "latitude": "", "longitude": "", "city_name": "", "city_jpdcode": ""} for i in range(3, 5)], "next_token": "", "total_records": 5},
    ]

    mock_db = AsyncMock()
    mock_db.execute = AsyncMock()
    mock_db.flush = AsyncMock()

    count = await sync_hotels(mock_client, mock_db, page_size=3)

    assert count == 5
    assert mock_client.hotel_portfolio.await_count == 2


# ---------------------------------------------------------------------------
# sync_catalogue
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_sync_catalogue_syncs_all_types():
    """Currencies, countries, hotel categories, and board types are synced."""
    mock_client = AsyncMock()
    mock_client.generic_data_catalogue.side_effect = [
        [{"code": "EUR", "name": "Euro"}],
        [{"code": "ES", "name": "Spain"}],
    ]
    mock_client.hotel_catalogue_data.return_value = {
        "hotel_categories": [{"code": "5est", "name": "5 Stars"}],
        "board_types": [{"code": "AD", "name": "Bed & Breakfast"}],
    }

    mock_db = AsyncMock()
    mock_db.execute = AsyncMock()
    mock_db.flush = AsyncMock()

    counts = await sync_catalogue(mock_client, mock_db)

    assert counts["currencies"] == 1
    assert counts["countries"] == 1
    assert counts["hotel_categories"] == 1
    assert counts["board_types"] == 1


# ---------------------------------------------------------------------------
# get_zone_code
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_get_zone_code_exact_match():
    """Exact case-insensitive name match returns zone."""
    zone_mock = MagicMock()
    zone_mock.jpdcode = "JPD086855"
    zone_mock.code = "49435"
    zone_mock.name = "Barcelona"
    zone_mock.area_type = "CTY"

    mock_db = AsyncMock()
    result_mock = MagicMock()
    result_mock.scalar_one_or_none.return_value = zone_mock
    mock_db.execute = AsyncMock(return_value=result_mock)

    result = await get_zone_code(mock_db, "barcelona")

    assert result is not None
    assert result["code"] == "49435"
    assert result["name"] == "Barcelona"


@pytest.mark.asyncio
async def test_get_zone_code_no_match_returns_none():
    """No matching zone returns None."""
    mock_db = AsyncMock()
    # First query (exact) → None
    result_exact = MagicMock()
    result_exact.scalar_one_or_none.return_value = None
    # Second query (contains) → empty
    result_contains = MagicMock()
    result_contains.scalars.return_value.all.return_value = []

    mock_db.execute = AsyncMock(side_effect=[result_exact, result_contains])

    result = await get_zone_code(mock_db, "Nonexistent City")

    assert result is None


@pytest.mark.asyncio
async def test_get_zone_code_prefers_city_over_region():
    """When multiple matches, prefer CTY area_type."""
    mock_db = AsyncMock()
    # First query (exact) → None
    result_exact = MagicMock()
    result_exact.scalar_one_or_none.return_value = None

    # Second query (contains) → region + city
    region = MagicMock()
    region.jpdcode = "JPD001"
    region.code = "100"
    region.name = "Catalonia"
    region.area_type = "REG"

    city = MagicMock()
    city.jpdcode = "JPD002"
    city.code = "200"
    city.name = "Barcelona City"
    city.area_type = "CTY"

    result_contains = MagicMock()
    result_contains.scalars.return_value.all.return_value = [region, city]

    mock_db.execute = AsyncMock(side_effect=[result_exact, result_contains])

    result = await get_zone_code(mock_db, "Barcel")

    assert result is not None
    assert result["code"] == "200"
    assert result["area_type"] == "CTY"


# ---------------------------------------------------------------------------
# get_zone_candidates
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_get_zone_candidates_returns_multiple():
    """Returns list of matching zones for disambiguation."""
    z1 = MagicMock()
    z1.jpdcode = "JPD001"
    z1.code = "100"
    z1.name = "Barcelona"
    z1.area_type = "CTY"

    z2 = MagicMock()
    z2.jpdcode = "JPD002"
    z2.code = "200"
    z2.name = "Barcelona Province"
    z2.area_type = "REG"

    mock_db = AsyncMock()
    result_mock = MagicMock()
    result_mock.scalars.return_value.all.return_value = [z1, z2]
    mock_db.execute = AsyncMock(return_value=result_mock)

    candidates = await get_zone_candidates(mock_db, "Barcelona", limit=5)

    assert len(candidates) == 2
    assert candidates[0]["name"] == "Barcelona"
    assert candidates[1]["name"] == "Barcelona Province"


# ---------------------------------------------------------------------------
# Mock client static data methods
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_mock_client_zone_list():
    from juniper_ai.app.juniper.mock_client import MockJuniperClient

    client = MockJuniperClient()
    zones = await client.zone_list()

    assert len(zones) > 0
    assert all("jpdcode" in z for z in zones)
    assert all("name" in z for z in zones)
    assert any(z["name"] == "Barcelona" for z in zones)


@pytest.mark.asyncio
async def test_mock_client_hotel_portfolio():
    from juniper_ai.app.juniper.mock_client import MockJuniperClient

    client = MockJuniperClient()
    result = await client.hotel_portfolio()

    assert "hotels" in result
    assert "next_token" in result
    assert "total_records" in result
    assert len(result["hotels"]) == 5
    assert all("jp_code" in h for h in result["hotels"])


@pytest.mark.asyncio
async def test_mock_client_generic_data_catalogue():
    from juniper_ai.app.juniper.mock_client import MockJuniperClient

    client = MockJuniperClient()
    currencies = await client.generic_data_catalogue("CURRENCY")
    countries = await client.generic_data_catalogue("COUNTRIES")

    assert len(currencies) > 0
    assert any(c["code"] == "EUR" for c in currencies)
    assert len(countries) > 0
    assert any(c["code"] == "ES" for c in countries)


@pytest.mark.asyncio
async def test_resolve_destination_unique_via_get_zone_code():
    """When get_zone_code finds a match, status is unique."""
    with patch("juniper_ai.app.juniper.static_data.get_zone_code", new_callable=AsyncMock) as gz:
        gz.return_value = {"jpdcode": "JPD1", "code": "100", "name": "Test City", "area_type": "CTY"}
        out = await resolve_destination(AsyncMock(), "Test City", limit=5)
    assert out["status"] == "unique"
    assert out["best"]["code"] == "100"


@pytest.mark.asyncio
async def test_resolve_destination_ambiguous():
    with patch("juniper_ai.app.juniper.static_data.get_zone_code", new_callable=AsyncMock, return_value=None), \
         patch("juniper_ai.app.juniper.static_data.get_zone_candidates", new_callable=AsyncMock) as gc:
        gc.return_value = [
            {"jpdcode": "JPD_A", "code": "1", "name": "Foo East", "area_type": "BAR"},
            {"jpdcode": "JPD_B", "code": "2", "name": "Foo City", "area_type": "CTY"},
        ]
        out = await resolve_destination(AsyncMock(), "Foo", limit=8)
    assert out["status"] == "ambiguous"
    assert len(out["candidates"]) == 2
    # CTY should sort before BAR
    assert out["candidates"][0]["area_type"] == "CTY"


@pytest.mark.asyncio
async def test_expand_zone_jpdcodes_fetchall():
    mock_db = AsyncMock()
    rm = MagicMock()
    rm.fetchall.return_value = [("JPD_ROOT",), ("JPD_CHILD",)]
    mock_db.execute = AsyncMock(return_value=rm)
    out = await expand_zone_jpdcodes(mock_db, ["JPD_ROOT"])
    assert set(out) == {"JPD_ROOT", "JPD_CHILD"}
    mock_db.execute.assert_awaited_once()


@pytest.mark.asyncio
async def test_expand_zone_jpdcodes_empty_roots():
    mock_db = AsyncMock()
    assert await expand_zone_jpdcodes(mock_db, []) == []
    assert await expand_zone_jpdcodes(mock_db, ["", "   "]) == []
    mock_db.execute.assert_not_called()


@pytest.mark.asyncio
async def test_explain_catalog_lookup_board():
    mock_db = AsyncMock()
    row = MagicMock()
    row.code = "AD"
    row.name = "Breakfast"
    mock_db.get = AsyncMock(return_value=row)
    out = await explain_catalog_lookup(mock_db, "board", "AD")
    assert out["name"] == "Breakfast"


@pytest.mark.asyncio
async def test_list_hotels_in_zone_jpdcodes_respects_limit():
    h1 = MagicMock()
    h1.jp_code = "JP1"
    h1.name = "H1"
    h1.zone_jpdcode = "Z1"
    h1.category_type = ""
    h1.city_name = ""

    with patch("juniper_ai.app.juniper.static_data.expand_zone_jpdcodes", new_callable=AsyncMock) as ex:
        ex.return_value = ["Z1"]
        mock_db = AsyncMock()
        result_mock = MagicMock()
        result_mock.scalars.return_value.all.return_value = [h1]
        mock_db.execute = AsyncMock(return_value=result_mock)
        payload = await list_hotels_in_zone_jpdcodes(
            mock_db, ["ZROOT"], limit=5, offset=0, expand_descendants=True,
        )
    assert len(payload["hotels"]) == 1
    assert payload["hotels"][0]["jp_code"] == "JP1"
    assert payload["has_more"] is False


@pytest.mark.asyncio
async def test_mock_client_hotel_catalogue_data():
    from juniper_ai.app.juniper.mock_client import MockJuniperClient

    client = MockJuniperClient()
    result = await client.hotel_catalogue_data()

    assert "hotel_categories" in result
    assert "board_types" in result
    assert len(result["hotel_categories"]) > 0
    assert len(result["board_types"]) > 0
