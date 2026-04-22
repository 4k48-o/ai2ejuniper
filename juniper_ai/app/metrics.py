"""Minimal Prometheus-compatible metrics (no external dependencies)."""

import threading
from collections import defaultdict


class Counter:
    """Thread-safe counter with optional labels."""

    def __init__(self, name: str, help_text: str, labels: tuple[str, ...] = ()):
        self.name = name
        self.help_text = help_text
        self.labels = labels
        self._values: dict[tuple[str, ...], float] = defaultdict(float)
        self._lock = threading.Lock()

    def inc(self, label_values: tuple[str, ...] = (), amount: float = 1.0) -> None:
        with self._lock:
            self._values[label_values] += amount

    def render(self) -> str:
        lines = [
            f"# HELP {self.name} {self.help_text}",
            f"# TYPE {self.name} counter",
        ]
        with self._lock:
            for label_vals, value in sorted(self._values.items()):
                if self.labels and label_vals:
                    label_str = ",".join(
                        f'{k}="{v}"' for k, v in zip(self.labels, label_vals)
                    )
                    lines.append(f"{self.name}{{{label_str}}} {value}")
                else:
                    lines.append(f"{self.name} {value}")
        return "\n".join(lines)


class Gauge:
    """Thread-safe gauge."""

    def __init__(self, name: str, help_text: str):
        self.name = name
        self.help_text = help_text
        self._value: float = 0.0
        self._lock = threading.Lock()

    def inc(self, amount: float = 1.0) -> None:
        with self._lock:
            self._value += amount

    def dec(self, amount: float = 1.0) -> None:
        with self._lock:
            self._value -= amount

    def set(self, value: float) -> None:
        with self._lock:
            self._value = value

    def render(self) -> str:
        with self._lock:
            val = self._value
        return (
            f"# HELP {self.name} {self.help_text}\n"
            f"# TYPE {self.name} gauge\n"
            f"{self.name} {val}"
        )


class Histogram:
    """Minimal histogram-like metric tracking count and sum (no buckets)."""

    def __init__(self, name: str, help_text: str):
        self.name = name
        self.help_text = help_text
        self._count: float = 0
        self._sum: float = 0.0
        self._lock = threading.Lock()

    def observe(self, value: float) -> None:
        with self._lock:
            self._count += 1
            self._sum += value

    def render(self) -> str:
        with self._lock:
            count = self._count
            total = self._sum
        return (
            f"# HELP {self.name} {self.help_text}\n"
            f"# TYPE {self.name} summary\n"
            f"{self.name}_count {count}\n"
            f"{self.name}_sum {total}"
        )


# ---------------------------------------------------------------------------
# Global metric instances
# ---------------------------------------------------------------------------

REQUEST_COUNTER = Counter(
    "juniperai_requests_total",
    "Total HTTP requests",
    labels=("method", "endpoint", "status"),
)

BOOKING_COUNTER = Counter(
    "juniperai_booking_total",
    "Total bookings",
    labels=("status",),
)

JUNIPER_API_LATENCY = Histogram(
    "juniperai_juniper_api_latency_seconds",
    "Juniper API call latency in seconds",
)

JUNIPER_API_ERRORS = Counter(
    "juniperai_juniper_api_errors_total",
    "Total Juniper API errors",
    labels=("error_type",),
)

ACTIVE_CONVERSATIONS = Gauge(
    "juniperai_active_conversations",
    "Number of currently active conversations",
)

# HotelAvail batch-level telemetry (ticket 1096690 HotelCodes path).
# One tick per batch; ``status`` captures the Juniper outcome so we can
# spot REQ_PRACTICE regressions, timeout spikes, and empty-result drift.
HOTEL_AVAIL_BATCHES = Counter(
    "juniper_hotel_avail_batches_total",
    "HotelAvail batch call outcomes (status = ok | empty | fault | timeout)",
    labels=("status",),
)

# JPCode candidate count per search — high values mean the local cache
# fan-out for a zone is large (and HotelAvail batching is doing real work).
HOTEL_AVAIL_CANDIDATES = Histogram(
    "juniper_hotel_avail_candidates",
    "JPCode candidate count per HotelAvail search (post-truncation)",
)


# ---------------------------------------------------------------------------
# Convenience recording functions
# ---------------------------------------------------------------------------


def record_request(method: str, endpoint: str, status: str) -> None:
    REQUEST_COUNTER.inc((method, endpoint, status))


def record_booking(status: str) -> None:
    BOOKING_COUNTER.inc((status,))


def record_juniper_latency(seconds: float) -> None:
    JUNIPER_API_LATENCY.observe(seconds)


def record_juniper_error(error_type: str) -> None:
    JUNIPER_API_ERRORS.inc((error_type,))


def record_hotel_avail_batch(status: str) -> None:
    """Record a HotelAvail batch outcome.

    ``status`` SHOULD be one of: ``ok``, ``empty``, ``fault``, ``timeout``.
    """
    HOTEL_AVAIL_BATCHES.inc((status,))


def record_hotel_avail_candidates(count: int) -> None:
    HOTEL_AVAIL_CANDIDATES.observe(float(count))


# ---------------------------------------------------------------------------
# Render all metrics
# ---------------------------------------------------------------------------

ALL_METRICS = [
    REQUEST_COUNTER,
    BOOKING_COUNTER,
    JUNIPER_API_LATENCY,
    JUNIPER_API_ERRORS,
    ACTIVE_CONVERSATIONS,
    HOTEL_AVAIL_BATCHES,
    HOTEL_AVAIL_CANDIDATES,
]


def render_metrics() -> str:
    """Return all metrics in Prometheus text exposition format."""
    return "\n\n".join(m.render() for m in ALL_METRICS) + "\n"
