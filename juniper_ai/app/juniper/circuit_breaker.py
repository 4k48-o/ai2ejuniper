"""Simple in-memory circuit breaker for Juniper API calls."""

import logging
import time
from enum import Enum

logger = logging.getLogger(__name__)


class CircuitState(str, Enum):
    CLOSED = "closed"  # normal operation
    OPEN = "open"  # failing, reject requests
    HALF_OPEN = "half_open"  # allow one probe


class CircuitOpenError(Exception):
    """Raised when the circuit breaker is open."""

    def __init__(self, retry_after: int):
        self.retry_after = retry_after
        super().__init__(f"Circuit breaker open. Retry after {retry_after}s.")


class CircuitBreaker:
    """Track consecutive Juniper API failures and trip the circuit.

    - Opens after ``failure_threshold`` failures within ``failure_window`` seconds.
    - Stays open for ``recovery_timeout`` seconds, then moves to half-open.
    - In half-open state a single success closes the circuit; a failure re-opens it.
    """

    def __init__(
        self,
        failure_threshold: int = 5,
        failure_window: int = 60,
        recovery_timeout: int = 30,
    ):
        self.failure_threshold = failure_threshold
        self.failure_window = failure_window
        self.recovery_timeout = recovery_timeout

        self._state = CircuitState.CLOSED
        self._failure_timestamps: list[float] = []
        self._opened_at: float = 0.0

    @property
    def state(self) -> CircuitState:
        if self._state == CircuitState.OPEN:
            if time.monotonic() - self._opened_at >= self.recovery_timeout:
                self._state = CircuitState.HALF_OPEN
                logger.info("Circuit breaker moving to HALF_OPEN")
        return self._state

    def check(self) -> None:
        """Call before making a Juniper API request.

        Raises ``CircuitOpenError`` if the circuit is open.
        """
        current = self.state
        if current == CircuitState.OPEN:
            retry_after = int(
                self.recovery_timeout - (time.monotonic() - self._opened_at)
            )
            raise CircuitOpenError(retry_after=max(retry_after, 1))
        # CLOSED and HALF_OPEN both allow the request through

    def record_success(self) -> None:
        """Record a successful API call."""
        if self._state in (CircuitState.HALF_OPEN, CircuitState.OPEN):
            logger.info("Circuit breaker closing after successful probe")
        self._state = CircuitState.CLOSED
        self._failure_timestamps.clear()

    def record_failure(self) -> None:
        """Record a failed API call."""
        now = time.monotonic()

        if self._state == CircuitState.HALF_OPEN:
            # Probe failed — re-open immediately
            logger.warning("Circuit breaker re-opening after failed probe")
            self._state = CircuitState.OPEN
            self._opened_at = now
            return

        # Trim old failures outside the window
        cutoff = now - self.failure_window
        self._failure_timestamps = [t for t in self._failure_timestamps if t > cutoff]
        self._failure_timestamps.append(now)

        if len(self._failure_timestamps) >= self.failure_threshold:
            logger.warning(
                "Circuit breaker OPEN after %d failures in %ds",
                len(self._failure_timestamps),
                self.failure_window,
            )
            self._state = CircuitState.OPEN
            self._opened_at = now


# Module-level singleton for the Juniper API
juniper_breaker = CircuitBreaker()
