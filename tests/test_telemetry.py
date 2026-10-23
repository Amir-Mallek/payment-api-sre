import json
import logging
import sys

from opentelemetry import metrics, trace

from app.config import Settings
from app.telemetry import JsonFormatter, Telemetry, configure_logging


def _record(msg="hello", **extra):
    record = logging.LogRecord("test", logging.INFO, __file__, 1, msg, None, None)
    for key, value in extra.items():
        setattr(record, key, value)
    return record


def test_json_formatter_without_span():
    payload = json.loads(JsonFormatter("svc").format(_record(order_id=42)))
    assert payload["message"] == "hello"
    assert payload["service"] == "svc"
    assert payload["order_id"] == 42
    assert "trace_id" not in payload


def test_json_formatter_injects_trace_context():
    tracer = trace.get_tracer("test")
    with tracer.start_as_current_span("unit") as span:
        payload = json.loads(JsonFormatter().format(_record()))
        expected = format(span.get_span_context().trace_id, "032x")
    assert payload["trace_id"] == expected
    assert len(payload["span_id"]) == 16


def test_json_formatter_includes_exception():
    try:
        raise RuntimeError("boom")
    except RuntimeError:
        record = _record()
        record.exc_info = sys.exc_info()
    payload = json.loads(JsonFormatter().format(record))
    assert "RuntimeError: boom" in payload["exception"]


def test_configure_logging_installs_json_handler():
    configure_logging(Settings())
    handlers = logging.getLogger().handlers
    assert len(handlers) == 1
    assert isinstance(handlers[0].formatter, JsonFormatter)
    assert logging.getLogger("uvicorn.access").disabled


def test_otlp_exporter_is_configured_when_endpoint_set(monkeypatch):
    captured = []
    monkeypatch.setattr(Telemetry, "_initialized", False)
    monkeypatch.setattr(trace, "set_tracer_provider", captured.append)
    monkeypatch.setattr(metrics, "set_meter_provider", lambda provider: None)
    Telemetry(Settings(otlp_endpoint="http://localhost:4317"))
    processors = captured[0]._active_span_processor._span_processors
    assert processors, "an OTLP span processor should be registered"
    assert Telemetry._initialized


def test_settings_read_environment(monkeypatch):
    monkeypatch.setenv("FLAKY_ERROR_RATE", "0.42")
    monkeypatch.setenv("OTEL_SERVICE_NAME", "custom")
    settings = Settings()
    assert settings.flaky_error_rate == 0.42
    assert settings.service_name == "custom"
