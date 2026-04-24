"""§11.8 follow-up — normalise Juniper response ``Errors`` handling.

Regression lock for the UAT sandbox dual-city run where Dubai's
``NO_AVAIL_FOUND`` (a soft "no inventory for this query" outcome) was
being raised as a fatal ``JuniperFaultError`` and aborting the whole
multi-batch search. It must become ``NoResultsError`` so the
``_run_batch`` tolerance path in ``hotel_avail`` swallows it the same
way it swallows Palma's empty-``HotelOption`` response.
"""

from types import SimpleNamespace

import pytest

from juniper_ai.app.juniper.client import JuniperClient
from juniper_ai.app.juniper.exceptions import JuniperFaultError, NoResultsError


def _errors_response(code: str, text: str = "") -> SimpleNamespace:
    """Build a minimal zeep-like response with an ``Errors/Error[*]`` node."""
    return SimpleNamespace(
        Errors=SimpleNamespace(
            Error=[SimpleNamespace(Code=code, Text=text)],
        ),
    )


def test_raise_if_response_errors_noop_when_no_errors_node():
    """Happy path: plain responses with no ``Errors`` block pass through."""
    response = SimpleNamespace(Results=SimpleNamespace(HotelResult=[]))
    # Should not raise.
    JuniperClient._raise_if_response_errors("HotelAvail", response)


def test_raise_if_response_errors_noop_when_errors_node_empty():
    """An empty ``Errors`` container (no ``Error`` children) is also fine."""
    response = SimpleNamespace(Errors=SimpleNamespace(Error=[]))
    JuniperClient._raise_if_response_errors("HotelAvail", response)


def test_no_avail_found_becomes_no_results_error():
    """UAT reproduction (Dubai city): supplier returns
    ``<Errors><Error Code="NO_AVAIL_FOUND"/></Errors>`` instead of an
    empty ``HotelOption`` list. Must be caught as NoResultsError so the
    per-batch tolerance path swallows it."""
    response = _errors_response("NO_AVAIL_FOUND", " No availability was found")
    with pytest.raises(NoResultsError) as excinfo:
        JuniperClient._raise_if_response_errors("HotelAvail", response)
    assert "NO_AVAIL_FOUND" in str(excinfo.value)
    assert "HotelAvail" in str(excinfo.value)


def test_no_avail_found_single_error_not_list():
    """zeep sometimes delivers a single ``Error`` as a bare object (not a
    list of one) — same code path must still convert to NoResultsError."""
    response = SimpleNamespace(
        Errors=SimpleNamespace(
            Error=SimpleNamespace(Code="NO_AVAIL_FOUND", Text="no avail"),
        ),
    )
    with pytest.raises(NoResultsError):
        JuniperClient._raise_if_response_errors("HotelAvail", response)


def test_req_practice_stays_fatal():
    """Hard request-shape errors (REQ_PRACTICE, AUTH_FAILED, etc.) MUST
    still surface as ``JuniperFaultError`` — they signal a config /
    integration bug that the retry-tolerance path must not hide."""
    response = _errors_response("REQ_PRACTICE", "parameter [DestinationZone]")
    with pytest.raises(JuniperFaultError) as excinfo:
        JuniperClient._raise_if_response_errors("HotelAvail", response)
    assert excinfo.value.fault_code == "REQ_PRACTICE"


def test_unknown_error_code_stays_fatal():
    """Conservative default: any unseen error code is treated as fatal.
    We explicitly allow-list soft codes in ``_SOFT_NO_RESULT_CODES`` so
    adding a new one is a deliberate review gate."""
    response = _errors_response("WEIRD_NEW_THING", "spooky")
    with pytest.raises(JuniperFaultError) as excinfo:
        JuniperClient._raise_if_response_errors("HotelAvail", response)
    assert excinfo.value.fault_code == "WEIRD_NEW_THING"


def test_soft_code_list_only_contains_no_avail_found_for_now():
    """Changing the allow-list is a design decision — lock the current
    membership so future edits to ``_SOFT_NO_RESULT_CODES`` go through
    code review and a test update rather than a silent broadening of
    what counts as 'soft-fail'."""
    assert JuniperClient._SOFT_NO_RESULT_CODES == frozenset({"NO_AVAIL_FOUND"})
