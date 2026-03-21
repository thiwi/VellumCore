"""Shared structured logging and OpenTelemetry setup helpers."""

from __future__ import annotations

import json
import logging
import os
from datetime import datetime, timezone
from typing import Any, Iterable


_LOGGING_CONFIGURED = False
_OTEL_PROVIDER_CONFIGURED = False
_HTTPX_INSTRUMENTED = False
_CELERY_INSTRUMENTED = False
_SQL_ENGINES_INSTRUMENTED: set[int] = set()


_RESERVED_RECORD_FIELDS = {
    "name",
    "msg",
    "args",
    "levelname",
    "levelno",
    "pathname",
    "filename",
    "module",
    "exc_info",
    "exc_text",
    "stack_info",
    "lineno",
    "funcName",
    "created",
    "msecs",
    "relativeCreated",
    "thread",
    "threadName",
    "processName",
    "process",
    "message",
    "asctime",
}


class JsonLogFormatter(logging.Formatter):
    """JSON formatter with trace correlation fields when available."""

    def __init__(self, *, service_name: str) -> None:
        super().__init__()
        self.service_name = service_name

    def format(self, record: logging.LogRecord) -> str:
        payload: dict[str, Any] = {
            "timestamp": datetime.now(timezone.utc).isoformat(),
            "service": self.service_name,
            "level": record.levelname,
            "logger": record.name,
            "message": record.getMessage(),
        }
        trace_id, span_id = _current_trace_context()
        if trace_id is not None and span_id is not None:
            payload["trace_id"] = trace_id
            payload["span_id"] = span_id

        extras = {
            key: value
            for key, value in record.__dict__.items()
            if key not in _RESERVED_RECORD_FIELDS and not key.startswith("_")
        }
        if extras:
            payload["extra"] = extras

        if record.exc_info:
            payload["exception"] = self.formatException(record.exc_info)
        return json.dumps(payload, default=str, separators=(",", ":"))


def configure_logging(service_name: str) -> None:
    """Configure process-wide JSON logging once."""
    global _LOGGING_CONFIGURED
    if _LOGGING_CONFIGURED:
        return

    level = os.getenv("LOG_LEVEL", "INFO").upper()
    handler = logging.StreamHandler()
    handler.setFormatter(JsonLogFormatter(service_name=service_name))

    root_logger = logging.getLogger()
    root_logger.handlers.clear()
    root_logger.addHandler(handler)
    root_logger.setLevel(level)

    for logger_name in (
        "uvicorn",
        "uvicorn.error",
        "uvicorn.access",
        "celery",
        "celery.worker",
        "celery.app.trace",
    ):
        logger = logging.getLogger(logger_name)
        logger.handlers.clear()
        logger.propagate = True

    _LOGGING_CONFIGURED = True
    logging.getLogger(__name__).info("logging_configured")


def init_telemetry(
    *,
    service_name: str,
    fastapi_app: Any | None = None,
    instrument_httpx: bool = False,
    instrument_celery: bool = False,
    sql_engines: Iterable[Any] | None = None,
) -> None:
    """Initialize optional OpenTelemetry exporter/instrumentation."""
    global _OTEL_PROVIDER_CONFIGURED, _HTTPX_INSTRUMENTED, _CELERY_INSTRUMENTED
    if not _env_bool("OTEL_ENABLED", default=True):
        return

    logger = logging.getLogger(__name__)
    try:
        from opentelemetry import trace
        from opentelemetry.exporter.otlp.proto.grpc.trace_exporter import (
            OTLPSpanExporter,
        )
        from opentelemetry.instrumentation.celery import CeleryInstrumentor
        from opentelemetry.instrumentation.fastapi import FastAPIInstrumentor
        from opentelemetry.instrumentation.httpx import HTTPXClientInstrumentor
        from opentelemetry.instrumentation.sqlalchemy import SQLAlchemyInstrumentor
        from opentelemetry.sdk.resources import Resource
        from opentelemetry.sdk.trace import TracerProvider
        from opentelemetry.sdk.trace.export import BatchSpanProcessor
    except ModuleNotFoundError:
        logger.warning("otel_packages_missing")
        return

    if not _OTEL_PROVIDER_CONFIGURED:
        endpoint = os.getenv("OTEL_EXPORTER_OTLP_ENDPOINT", "http://otel-collector:4317")
        insecure = _env_bool("OTEL_EXPORTER_OTLP_INSECURE", default=True)
        try:
            resource = Resource.create(
                {
                    "service.name": service_name,
                    "service.namespace": os.getenv("OTEL_SERVICE_NAMESPACE", "vellum-core"),
                    "deployment.environment": os.getenv("ENVIRONMENT", "dev"),
                }
            )
            provider = TracerProvider(resource=resource)
            provider.add_span_processor(
                BatchSpanProcessor(
                    OTLPSpanExporter(
                        endpoint=endpoint,
                        insecure=insecure,
                    )
                )
            )
            try:
                trace.set_tracer_provider(provider)
            except Exception:
                # Provider may already be configured by another module.
                pass
            _OTEL_PROVIDER_CONFIGURED = True
            logger.info(
                "otel_provider_configured",
                extra={"endpoint": endpoint, "insecure": insecure},
            )
        except Exception:
            logger.exception("otel_provider_configuration_failed")
            return

    try:
        if fastapi_app is not None and not getattr(
            fastapi_app.state, "_otel_fastapi_instrumented", False
        ):
            excluded = os.getenv("OTEL_FASTAPI_EXCLUDED_URLS", "/healthz,/metrics")
            FastAPIInstrumentor.instrument_app(fastapi_app, excluded_urls=excluded)
            fastapi_app.state._otel_fastapi_instrumented = True

        if instrument_httpx and not _HTTPX_INSTRUMENTED:
            HTTPXClientInstrumentor().instrument()
            _HTTPX_INSTRUMENTED = True

        if instrument_celery and not _CELERY_INSTRUMENTED:
            CeleryInstrumentor().instrument()
            _CELERY_INSTRUMENTED = True

        if sql_engines:
            for engine in sql_engines:
                engine_id = id(engine)
                if engine_id in _SQL_ENGINES_INSTRUMENTED:
                    continue
                sync_engine = getattr(engine, "sync_engine", None)
                if sync_engine is None:
                    continue
                SQLAlchemyInstrumentor().instrument(engine=sync_engine)
                _SQL_ENGINES_INSTRUMENTED.add(engine_id)
    except Exception:
        logger.exception("otel_instrumentation_failed")


def _current_trace_context() -> tuple[str | None, str | None]:
    try:
        from opentelemetry import trace
    except ModuleNotFoundError:
        return None, None
    try:
        span = trace.get_current_span()
        context = span.get_span_context()
        if context is None or not context.is_valid:
            return None, None
        return f"{context.trace_id:032x}", f"{context.span_id:016x}"
    except Exception:
        return None, None


def _env_bool(name: str, *, default: bool) -> bool:
    raw = os.getenv(name)
    if raw is None:
        return default
    value = raw.strip().lower()
    if value in {"1", "true", "yes", "on"}:
        return True
    if value in {"0", "false", "no", "off"}:
        return False
    return default
