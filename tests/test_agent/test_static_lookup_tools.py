"""Tests for read-only static lookup Agent tools."""

import json
from contextlib import asynccontextmanager
from unittest.mock import AsyncMock, MagicMock, patch

import pytest


@pytest.mark.asyncio
async def test_resolve_destination_tool_returns_json():
    payload = {
        "status": "unique",
        "query": "Barcelona",
        "best": {"jpdcode": "JPD1", "code": "49435", "name": "Barcelona", "area_type": "CTY"},
        "candidates": [{"hint": "x"}],
        "hint": None,
    }

    @asynccontextmanager
    async def _fake_session():
        yield MagicMock()

    with patch("juniper_ai.app.agent.tools.static_lookup_tools.async_session", _fake_session), \
         patch(
             "juniper_ai.app.agent.tools.static_lookup_tools.static_data_layer.resolve_destination",
             new_callable=AsyncMock,
             return_value=payload,
         ):
        from juniper_ai.app.agent.tools.static_lookup_tools import resolve_destination

        raw = await resolve_destination.ainvoke({"destination_text": "Barcelona", "max_candidates": 5})

    data = json.loads(raw)
    assert data["status"] == "unique"
    assert data["best"]["code"] == "49435"


@pytest.mark.asyncio
async def test_list_hotels_for_zones_requires_jpd():
    from juniper_ai.app.agent.tools.static_lookup_tools import list_hotels_for_zones

    raw = await list_hotels_for_zones.ainvoke({"zone_jpdcodes": "   ", "limit": 10, "offset": 0})
    data = json.loads(raw)
    assert "error" in data


@pytest.mark.asyncio
async def test_explain_catalog_tool_found():
    @asynccontextmanager
    async def _fake_session():
        yield MagicMock()

    with patch("juniper_ai.app.agent.tools.static_lookup_tools.async_session", _fake_session), \
         patch(
             "juniper_ai.app.agent.tools.static_lookup_tools.static_data_layer.explain_catalog_lookup",
             new_callable=AsyncMock,
             return_value={"code_type": "board", "code": "AD", "name": "Breakfast"},
         ):
        from juniper_ai.app.agent.tools.static_lookup_tools import explain_catalog

        raw = await explain_catalog.ainvoke({"code_type": "board", "code": "AD"})

    data = json.loads(raw)
    assert data["found"] is True
    assert data["name"] == "Breakfast"


@pytest.mark.asyncio
async def test_explain_catalog_tool_not_found():
    @asynccontextmanager
    async def _fake_session():
        yield MagicMock()

    with patch("juniper_ai.app.agent.tools.static_lookup_tools.async_session", _fake_session), \
         patch(
             "juniper_ai.app.agent.tools.static_lookup_tools.static_data_layer.explain_catalog_lookup",
             new_callable=AsyncMock,
             return_value=None,
         ):
        from juniper_ai.app.agent.tools.static_lookup_tools import explain_catalog

        raw = await explain_catalog.ainvoke({"code_type": "board", "code": "ZZ"})

    data = json.loads(raw)
    assert data["found"] is False


@pytest.mark.asyncio
async def test_graph_includes_static_tools():
    from juniper_ai.app.agent.graph import ALL_TOOLS

    names = {t.name for t in ALL_TOOLS}
    assert "resolve_destination" in names
    assert "list_hotels_for_zones" in names
    assert "explain_catalog" in names
