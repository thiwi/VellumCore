"""Tests for Observability."""

from __future__ import annotations

import json
import logging

from vellum_core.observability import JsonLogFormatter, _env_bool, init_telemetry


def test_env_bool_parsing(monkeypatch) -> None:  # type: ignore[no-untyped-def]
    monkeypatch.setenv("X_BOOL", "true")
    assert _env_bool("X_BOOL", default=False) is True
    monkeypatch.setenv("X_BOOL", "0")
    assert _env_bool("X_BOOL", default=True) is False
    monkeypatch.setenv("X_BOOL", "invalid")
    assert _env_bool("X_BOOL", default=True) is True


def test_json_log_formatter_outputs_structured_json() -> None:
    formatter = JsonLogFormatter(service_name="svc")
    record = logging.LogRecord(
        name="test.logger",
        level=logging.INFO,
        pathname=__file__,
        lineno=10,
        msg="hello",
        args=(),
        exc_info=None,
    )
    record.proof_id = "p1"
    payload = json.loads(formatter.format(record))
    assert payload["service"] == "svc"
    assert payload["level"] == "INFO"
    assert payload["logger"] == "test.logger"
    assert payload["message"] == "hello"
    assert payload["extra"]["proof_id"] == "p1"


def test_init_telemetry_noop_when_disabled(monkeypatch) -> None:  # type: ignore[no-untyped-def]
    monkeypatch.setenv("OTEL_ENABLED", "false")
    init_telemetry(service_name="svc")
