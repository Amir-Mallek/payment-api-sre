"""OpenTelemetry setup: traces (OTLP), metrics (Prometheus /metrics) and JSON logs with trace_id."""

from __future__ import annotations

import json
import logging
import sys
from datetime import UTC, datetime

from opentelemetry import metrics, trace
from opentelemetry.exporter.prometheus import PrometheusMetricReader
from opentelemetry.instrumentation.fastapi import FastAPIInstrumentor
from opentelemetry.metrics import NoOpMeterProvider
from opentelemetry.sdk.metrics import MeterProvider
from opentelemetry.sdk.metrics.view import ExplicitBucketHistogramAggregation, View
from opentelemetry.sdk.resources import Resource
from opentelemetry.sdk.trace import TracerProvider
from opentelemetry.sdk.trace.export import BatchSpanProcessor

from app.config import Settings

# Bucket boundaries in seconds; 0.2 s is the latency SLO threshold.
LATENCY_BUCKETS = (0.005, 0.01, 0.025, 0.05, 0.1, 0.15, 0.2, 0.3, 0.5, 0.75, 1.0, 2.5, 5.0)

_STANDARD_RECORD_ATTRS = set(vars(logging.makeLogRecord({}))) | {"message", "asctime"}


class JsonFormatter(logging.Formatter):
    """Render log records as one JSON object per line, enriched with the active trace context."""

    def __init__(self, service_name: str = "payment-api") -> None:
        super().__init__()
        self.service_name = service_name

    def format(self, record: logging.LogRecord) -> str:
        payload = {
            "timestamp": datetime.fromtimestamp(record.created, tz=UTC).isoformat(),
            "level": record.levelname,
            "logger": record.name,
            "message": record.getMessage(),
            "service": self.service_name,
        }
        span_context = trace.get_current_span().get_span_context()
        if span_context.is_valid:
            payload["trace_id"] = format(span_context.trace_id, "032x")
            payload["span_id"] = format(span_context.span_id, "016x")
        for key, value in vars(record).items():
            if key not in _STANDARD_RECORD_ATTRS and not key.startswith("_"):
                payload[key] = value
        if record.exc_info:
            payload["exception"] = self.formatException(record.exc_info)
        return json.dumps(payload, default=str)


def configure_logging(settings: Settings) -> None:
    handler = logging.StreamHandler(sys.stdout)
    handler.setFormatter(JsonFormatter(settings.service_name))
    root = logging.getLogger()
    root.handlers[:] = [handler]
    root.setLevel(logging.INFO)
    # Requests are logged by our own middleware, with the trace_id.
    logging.getLogger("uvicorn.access").disabled = True
    logging.getLogger("httpx").setLevel(logging.WARNING)


class Telemetry:
    """Holds the providers and the RED instruments used by the HTTP middleware."""

    _initialized = False

    def __init__(self, settings: Settings) -> None:
        self.settings = settings
        resource = Resource.create(
            {
                "service.name": settings.service_name,
                "service.version": settings.version,
                "deployment.environment": settings.environment,
            }
        )
        if not Telemetry._initialized:
            tracer_provider = TracerProvider(resource=resource)
            if settings.otlp_endpoint:
                from opentelemetry.exporter.otlp.proto.grpc.trace_exporter import OTLPSpanExporter

                tracer_provider.add_span_processor(
                    BatchSpanProcessor(OTLPSpanExporter(endpoint=settings.otlp_endpoint, insecure=True))
                )
            trace.set_tracer_provider(tracer_provider)

            latency_view = View(
                instrument_name="http.server.request.duration",
                aggregation=ExplicitBucketHistogramAggregation(LATENCY_BUCKETS),
            )
            meter_provider = MeterProvider(
                resource=resource, metric_readers=[PrometheusMetricReader()], views=[latency_view]
            )
            metrics.set_meter_provider(meter_provider)
            Telemetry._initialized = True

        meter = metrics.get_meter("payment-api")
        # Exposed as http_server_requests_total and http_server_request_duration_seconds.
        self.requests = meter.create_counter("http.server.requests", description="HTTP requests handled")
        self.duration = meter.create_histogram(
            "http.server.request.duration", unit="s", description="HTTP request latency"
        )
        self.payments = meter.create_counter("payments.processed", description="Payments by outcome")
        self.in_flight = meter.create_up_down_counter(
            "http.server.active_requests", description="Requests currently being processed"
        )

    def instrument(self, app) -> None:
        # Traces only: RED metrics come from our middleware so that the SLO buckets are controlled.
        FastAPIInstrumentor.instrument_app(
            app, tracer_provider=trace.get_tracer_provider(), meter_provider=NoOpMeterProvider()
        )
