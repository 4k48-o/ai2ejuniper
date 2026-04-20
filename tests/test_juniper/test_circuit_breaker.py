"""Tests for the circuit breaker."""

import time
from unittest.mock import patch

import pytest

from juniper_ai.app.juniper.circuit_breaker import (
    CircuitBreaker,
    CircuitOpenError,
    CircuitState,
)


@pytest.fixture
def breaker():
    return CircuitBreaker(failure_threshold=5, failure_window=60, recovery_timeout=30)


def test_circuit_starts_closed(breaker):
    assert breaker.state == CircuitState.CLOSED


def test_record_success_stays_closed(breaker):
    breaker.record_success()
    assert breaker.state == CircuitState.CLOSED


def test_opens_after_threshold_failures(breaker):
    for _ in range(5):
        breaker.record_failure()
    assert breaker.state == CircuitState.OPEN


def test_does_not_open_below_threshold(breaker):
    for _ in range(4):
        breaker.record_failure()
    assert breaker.state == CircuitState.CLOSED


def test_rejects_when_open(breaker):
    for _ in range(5):
        breaker.record_failure()

    with pytest.raises(CircuitOpenError) as exc_info:
        breaker.check()
    assert exc_info.value.retry_after >= 1


def test_check_passes_when_closed(breaker):
    # Should not raise
    breaker.check()


def test_transitions_to_half_open_after_timeout(breaker):
    for _ in range(5):
        breaker.record_failure()
    assert breaker.state == CircuitState.OPEN

    # Simulate time passing beyond recovery_timeout
    breaker._opened_at = time.monotonic() - 31  # 31 seconds ago, timeout is 30
    assert breaker.state == CircuitState.HALF_OPEN


def test_closes_on_success_in_half_open(breaker):
    for _ in range(5):
        breaker.record_failure()

    # Move to half-open
    breaker._opened_at = time.monotonic() - 31
    assert breaker.state == CircuitState.HALF_OPEN

    breaker.record_success()
    assert breaker.state == CircuitState.CLOSED


def test_reopens_on_failure_in_half_open(breaker):
    for _ in range(5):
        breaker.record_failure()

    # Move to half-open
    breaker._opened_at = time.monotonic() - 31
    assert breaker.state == CircuitState.HALF_OPEN

    breaker.record_failure()
    assert breaker.state == CircuitState.OPEN


def test_half_open_allows_check(breaker):
    for _ in range(5):
        breaker.record_failure()

    breaker._opened_at = time.monotonic() - 31
    assert breaker.state == CircuitState.HALF_OPEN

    # check() should not raise in half-open state
    breaker.check()


def test_success_clears_failure_timestamps(breaker):
    for _ in range(3):
        breaker.record_failure()
    assert len(breaker._failure_timestamps) == 3

    breaker.record_success()
    assert len(breaker._failure_timestamps) == 0
