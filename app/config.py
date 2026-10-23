"""Runtime settings, read from environment variables."""

from __future__ import annotations

import os
from dataclasses import dataclass, field


def _float(name: str, default: float) -> float:
    return float(os.getenv(name, default))


@dataclass
class Settings:
    service_name: str = field(default_factory=lambda: os.getenv("OTEL_SERVICE_NAME", "payment-api"))
    version: str = field(default_factory=lambda: os.getenv("APP_VERSION", "dev"))
    environment: str = field(default_factory=lambda: os.getenv("APP_ENV", "local"))
    # OTLP gRPC endpoint of the OpenTelemetry Collector; tracing export is disabled when empty.
    otlp_endpoint: str = field(default_factory=lambda: os.getenv("OTEL_EXPORTER_OTLP_ENDPOINT", ""))
    # /checkout: nominal latency window, plus a small share of very slow requests.
    checkout_min_ms: float = field(default_factory=lambda: _float("CHECKOUT_MIN_MS", 20))
    checkout_max_ms: float = field(default_factory=lambda: _float("CHECKOUT_MAX_MS", 150))
    checkout_slow_ratio: float = field(default_factory=lambda: _float("CHECKOUT_SLOW_RATIO", 0.02))
    checkout_slow_ms: float = field(default_factory=lambda: _float("CHECKOUT_SLOW_MS", 900))
    # /flaky: probability of answering HTTP 500.
    flaky_error_rate: float = field(default_factory=lambda: _float("FLAKY_ERROR_RATE", 0.1))
    # Load shedding: answer 503 when more requests than this are in flight (0 disables it).
    max_in_flight: int = field(default_factory=lambda: int(os.getenv("MAX_IN_FLIGHT", "0")))
