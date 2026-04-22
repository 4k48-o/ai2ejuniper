"""§7: observability + error aggregation for JuniperClient.hotel_avail."""

from unittest.mock import AsyncMock, patch

import pytest

from juniper_ai.app.juniper.client import JuniperClient
from juniper_ai.app.juniper.exceptions import JuniperFaultError, NoResultsError


@pytest.fixture
def client():
    # __init__ is a no-op (lazy WSDL); safe to instantiate for method tests
    # that never touch the network.
    return JuniperClient()


@pytest.mark.asyncio
async def test_hotel_avail_records_candidates_and_per_batch_status(client):
    """Success path: per-batch ok/empty counter + candidates histogram."""
    # 3 batches: one with results, one empty, one with results.
    async def fake_batch(*, hotel_codes, batch_index, total_batches, **kw):
        if batch_index == 2:
            return []  # empty batch
        return [{"rate_plan_code": f"RPC_{batch_index}", "name": f"H{batch_index}"}]

    with patch.object(client, "_hotel_avail_batch", side_effect=fake_batch), \
         patch("juniper_ai.app.juniper.client.settings.hotel_avail_batch_size", 2), \
         patch("juniper_ai.app.juniper.client.settings.hotel_avail_batch_concurrency", 3), \
         patch("juniper_ai.app.juniper.client.settings.hotel_avail_max_candidates", 100), \
         patch("juniper_ai.app.juniper.client.record_hotel_avail_batch") as m_batch, \
         patch("juniper_ai.app.juniper.client.record_hotel_avail_candidates") as m_cand:
        codes = ["JP1", "JP2", "JP3", "JP4", "JP5"]  # -> 3 batches (2/2/1)
        result = await client.hotel_avail(
            hotel_codes=codes,
            check_in="2026-05-01",
            check_out="2026-05-03",
            adults=2,
        )

    assert len(result) == 2  # batches 1 and 3 returned 1 rate plan each
    m_cand.assert_called_once_with(5)
    statuses = [c.args[0] for c in m_batch.call_args_list]
    assert sorted(statuses) == ["empty", "ok", "ok"]


@pytest.mark.asyncio
async def test_hotel_avail_aggregates_fault_and_aborts(client, caplog):
    """Fault in one batch: counter=fault (once), single ERROR log, exception propagates."""
    async def fake_batch(*, hotel_codes, batch_index, total_batches, **kw):
        if batch_index == 2:
            raise JuniperFaultError("REQ_PRACTICE", "destination zone check")
        # Other batches would succeed, but gather cancels them after the
        # fault — so this branch should not be observed in the counter.
        return [{"rate_plan_code": "RPC_X"}]

    with patch.object(client, "_hotel_avail_batch", side_effect=fake_batch), \
         patch("juniper_ai.app.juniper.client.settings.hotel_avail_batch_size", 2), \
         patch("juniper_ai.app.juniper.client.settings.hotel_avail_batch_concurrency", 1), \
         patch("juniper_ai.app.juniper.client.settings.hotel_avail_max_candidates", 100), \
         patch("juniper_ai.app.juniper.client.record_hotel_avail_batch") as m_batch, \
         caplog.at_level("ERROR", logger="juniper_ai.app.juniper.client"):
        with pytest.raises(JuniperFaultError) as exc_info:
            await client.hotel_avail(
                hotel_codes=["JP1", "JP2", "JP3", "JP4"],
                check_in="2026-05-01",
                check_out="2026-05-03",
                adults=2,
            )

    assert exc_info.value.fault_code == "REQ_PRACTICE"
    # Exactly one ``fault`` record — even though multiple batches exist.
    fault_calls = [c for c in m_batch.call_args_list if c.args == ("fault",)]
    assert len(fault_calls) == 1

    # Aggregated single ERROR log with fault_code + batch context.
    fault_logs = [r for r in caplog.records if "Juniper fault" in r.getMessage()]
    assert len(fault_logs) == 1
    assert "REQ_PRACTICE" in fault_logs[0].getMessage()
    assert "aborting search" in fault_logs[0].getMessage()


@pytest.mark.asyncio
async def test_hotel_avail_all_empty_raises_no_results(client):
    """All batches empty → counter=empty x N, then NoResultsError bubbles up."""
    async def fake_batch(**kw):
        return []

    with patch.object(client, "_hotel_avail_batch", side_effect=fake_batch), \
         patch("juniper_ai.app.juniper.client.settings.hotel_avail_batch_size", 2), \
         patch("juniper_ai.app.juniper.client.settings.hotel_avail_batch_concurrency", 2), \
         patch("juniper_ai.app.juniper.client.settings.hotel_avail_max_candidates", 100), \
         patch("juniper_ai.app.juniper.client.record_hotel_avail_batch") as m_batch:
        with pytest.raises(NoResultsError):
            await client.hotel_avail(
                hotel_codes=["JP1", "JP2", "JP3"],
                check_in="2026-05-01",
                check_out="2026-05-03",
                adults=2,
            )

    statuses = [c.args[0] for c in m_batch.call_args_list]
    assert statuses == ["empty", "empty"]


# §8.1.3 — batch sharding boundaries at (batch_size=25): 20/21/50/51.
@pytest.mark.asyncio
@pytest.mark.parametrize(
    "n_codes,expected_batches,expected_last_size",
    [
        (20, 1, 20),   # under-fill → single batch
        (21, 1, 21),   # still fits (≤ batch_size)
        (25, 1, 25),   # exact fit
        (26, 2, 1),    # just over → two batches, tail of 1
        (50, 2, 25),   # exact 2×
        (51, 3, 1),    # tail of 1 again
    ],
)
async def test_hotel_avail_batch_sharding_boundaries(
    client, n_codes, expected_batches, expected_last_size,
):
    observed: list[int] = []

    async def capture_batch(*, hotel_codes, batch_index, total_batches, **kw):
        observed.append(len(hotel_codes))
        return [{"rate_plan_code": f"RPC_{batch_index}"}]

    codes = [f"JP{i:05d}" for i in range(n_codes)]

    with patch.object(client, "_hotel_avail_batch", side_effect=capture_batch), \
         patch("juniper_ai.app.juniper.client.settings.hotel_avail_batch_size", 25), \
         patch("juniper_ai.app.juniper.client.settings.hotel_avail_batch_concurrency", 3), \
         patch("juniper_ai.app.juniper.client.settings.hotel_avail_max_candidates", 200), \
         patch("juniper_ai.app.juniper.client.record_hotel_avail_batch"), \
         patch("juniper_ai.app.juniper.client.record_hotel_avail_candidates"):
        hotels = await client.hotel_avail(
            hotel_codes=codes,
            check_in="2026-05-01",
            check_out="2026-05-03",
            adults=2,
        )

    assert len(observed) == expected_batches
    assert observed[-1] == expected_last_size
    assert sum(observed) == n_codes
    assert len(hotels) == expected_batches  # one unique rate plan per batch


# §8.2.2 — all-fault path: first fault propagates, siblings cancelled, single fault counter.
@pytest.mark.asyncio
async def test_hotel_avail_all_batches_fault_propagates_once(client):
    async def always_fault(*, batch_index, **kw):
        raise JuniperFaultError("REQ_PRACTICE", "policy block")

    with patch.object(client, "_hotel_avail_batch", side_effect=always_fault), \
         patch("juniper_ai.app.juniper.client.settings.hotel_avail_batch_size", 2), \
         patch("juniper_ai.app.juniper.client.settings.hotel_avail_batch_concurrency", 1), \
         patch("juniper_ai.app.juniper.client.settings.hotel_avail_max_candidates", 100), \
         patch("juniper_ai.app.juniper.client.record_hotel_avail_batch") as m_batch:
        with pytest.raises(JuniperFaultError) as exc:
            await client.hotel_avail(
                hotel_codes=["JP1", "JP2", "JP3", "JP4"],
                check_in="2026-05-01",
                check_out="2026-05-03",
                adults=2,
            )

    assert exc.value.fault_code == "REQ_PRACTICE"
    # With concurrency=1 the first fault aborts gather before peers run,
    # so exactly one ``fault`` tick is expected.
    fault_ticks = [c for c in m_batch.call_args_list if c.args == ("fault",)]
    assert len(fault_ticks) == 1
