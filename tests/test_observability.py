"""Tests for Observability."""

from __future__ import annotations

import builtins
import json
import logging
import sys
from types import ModuleType, SimpleNamespace

from fastapi import FastAPI

import vellum_core.observability as observability
from vellum_core.observability import JsonLogFormatter, _env_bool, init_telemetry


def _install_fake_otel_modules(monkeypatch) -> None:  # type: ignore[no-untyped-def]
    def _ensure_module(name: str) -> ModuleType:
        module = sys.modules.get(name)
        if isinstance(module, ModuleType):
            return module
        module = ModuleType(name)
        monkeypatch.setitem(sys.modules, name, module)
        if "." in name:
            parent_name, child_name = name.rsplit(".", 1)
            parent = _ensure_module(parent_name)
            setattr(parent, child_name, module)
        return module

    otel_mod = _ensure_module("opentelemetry")

    class _TraceApi:
        @staticmethod
        def set_tracer_provider(_provider) -> None:
            return None

        @staticmethod
        def get_current_span() -> object:
            return SimpleNamespace(
                get_span_context=lambda: SimpleNamespace(is_valid=False),
            )

    otel_mod.trace = _TraceApi()

    exporter_mod = _ensure_module("opentelemetry.exporter.otlp.proto.grpc.trace_exporter")

    class OTLPSpanExporter:  # noqa: N801
        def __init__(self, **_kwargs) -> None:
            pass

    exporter_mod.OTLPSpanExporter = OTLPSpanExporter

    celery_mod = _ensure_module("opentelemetry.instrumentation.celery")
    fastapi_mod = _ensure_module("opentelemetry.instrumentation.fastapi")
    httpx_mod = _ensure_module("opentelemetry.instrumentation.httpx")
    sqlalchemy_mod = _ensure_module("opentelemetry.instrumentation.sqlalchemy")

    class _NoopInstrumentor:
        def instrument(self, **_kwargs) -> None:
            return None

    class _FastapiInstrumentor:
        @staticmethod
        def instrument_app(_app, **_kwargs) -> None:
            return None

    celery_mod.CeleryInstrumentor = _NoopInstrumentor
    httpx_mod.HTTPXClientInstrumentor = _NoopInstrumentor
    sqlalchemy_mod.SQLAlchemyInstrumentor = _NoopInstrumentor
    fastapi_mod.FastAPIInstrumentor = _FastapiInstrumentor

    resources_mod = _ensure_module("opentelemetry.sdk.resources")
    trace_sdk_mod = _ensure_module("opentelemetry.sdk.trace")
    trace_export_mod = _ensure_module("opentelemetry.sdk.trace.export")

    class Resource:  # noqa: N801
        @staticmethod
        def create(payload):  # type: ignore[no-untyped-def]
            return payload

    class TracerProvider:  # noqa: N801
        def __init__(self, resource=None) -> None:
            self.resource = resource

        def add_span_processor(self, _processor) -> None:
            return None

    class BatchSpanProcessor:  # noqa: N801
        def __init__(self, _exporter) -> None:
            return None

    resources_mod.Resource = Resource
    trace_sdk_mod.TracerProvider = TracerProvider
    trace_export_mod.BatchSpanProcessor = BatchSpanProcessor


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


def test_configure_logging_is_idempotent(monkeypatch) -> None:  # type: ignore[no-untyped-def]
    monkeypatch.setenv("LOG_LEVEL", "DEBUG")
    monkeypatch.setattr(observability, "_LOGGING_CONFIGURED", False)
    observability.configure_logging(service_name="svc")
    assert observability._LOGGING_CONFIGURED is True
    assert logging.getLogger().level == logging.DEBUG

    # Covers early-return branch when logging was already initialized.
    observability.configure_logging(service_name="svc")


def test_init_telemetry_warns_when_otel_packages_missing(monkeypatch) -> None:  # type: ignore[no-untyped-def]
    monkeypatch.setenv("OTEL_ENABLED", "true")
    monkeypatch.setattr(observability, "_OTEL_PROVIDER_CONFIGURED", False)
    monkeypatch.setattr(observability, "_HTTPX_INSTRUMENTED", False)
    monkeypatch.setattr(observability, "_CELERY_INSTRUMENTED", False)
    observability._SQL_ENGINES_INSTRUMENTED.clear()

    original_import = builtins.__import__

    def _raising_import(name, *args, **kwargs):  # type: ignore[no-untyped-def]
        if name.startswith("opentelemetry"):
            raise ModuleNotFoundError(name)
        return original_import(name, *args, **kwargs)

    monkeypatch.setattr(builtins, "__import__", _raising_import)
    observability.init_telemetry(service_name="svc")
    assert observability._OTEL_PROVIDER_CONFIGURED is False


def test_init_telemetry_instruments_fastapi_httpx_celery(monkeypatch) -> None:  # type: ignore[no-untyped-def]
    _install_fake_otel_modules(monkeypatch)
    monkeypatch.setenv("OTEL_ENABLED", "true")
    monkeypatch.setenv("OTEL_EXPORTER_OTLP_ENDPOINT", "http://localhost:4317")
    monkeypatch.setenv("OTEL_EXPORTER_OTLP_INSECURE", "true")
    monkeypatch.setattr(observability, "_OTEL_PROVIDER_CONFIGURED", False)
    monkeypatch.setattr(observability, "_HTTPX_INSTRUMENTED", False)
    monkeypatch.setattr(observability, "_CELERY_INSTRUMENTED", False)
    observability._SQL_ENGINES_INSTRUMENTED.clear()

    app = FastAPI()
    observability.init_telemetry(
        service_name="svc",
        fastapi_app=app,
        instrument_httpx=True,
        instrument_celery=True,
        sql_engines=[SimpleNamespace(sync_engine=None)],
    )
    assert observability._OTEL_PROVIDER_CONFIGURED is True
    assert observability._HTTPX_INSTRUMENTED is True
    assert observability._CELERY_INSTRUMENTED is True
    assert getattr(app.state, "_otel_fastapi_instrumented", False) is True

    # Covers branch where app/provider/instrumentors are already initialized.
    observability.init_telemetry(
        service_name="svc",
        fastapi_app=app,
        instrument_httpx=True,
        instrument_celery=True,
    )


def test_current_trace_context_valid_and_exception_paths(monkeypatch) -> None:  # type: ignore[no-untyped-def]
    fake_module = ModuleType("opentelemetry")

    class _Ctx:
        is_valid = True
        trace_id = 0xABC
        span_id = 0xDEF

    class _Span:
        @staticmethod
        def get_span_context() -> _Ctx:
            return _Ctx()

    trace_obj = SimpleNamespace(get_current_span=lambda: _Span())
    fake_module.trace = trace_obj
    monkeypatch.setitem(sys.modules, "opentelemetry", fake_module)
    trace_id, span_id = observability._current_trace_context()
    assert trace_id == f"{0xABC:032x}"
    assert span_id == f"{0xDEF:016x}"

    trace_obj_exc = SimpleNamespace(get_current_span=lambda: (_ for _ in ()).throw(RuntimeError("boom")))
    fake_module_exc = ModuleType("opentelemetry")
    fake_module_exc.trace = trace_obj_exc
    monkeypatch.setitem(sys.modules, "opentelemetry", fake_module_exc)
    assert observability._current_trace_context() == (None, None)
