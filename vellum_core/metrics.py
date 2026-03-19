from __future__ import annotations

from threading import Lock

from prometheus_client import CONTENT_TYPE_LATEST, Gauge, Histogram, generate_latest


vellum_proof_duration_seconds = Histogram(
    "vellum_proof_duration_seconds",
    "End-to-end proving duration in seconds.",
)

vellum_verify_duration_seconds = Histogram(
    "vellum_verify_duration_seconds",
    "Proof verification duration in seconds.",
)

vellum_native_verify_duration_seconds = Gauge(
    "vellum_native_verify_duration_seconds",
    "Native (non-ZK) verification baseline duration in seconds.",
)

_METRIC_LOCK = Lock()
_verify_total_seconds = 0.0
_verify_count = 0
_native_baseline_seconds = 0.0


def observe_proof_duration(seconds: float) -> None:
    vellum_proof_duration_seconds.observe(seconds)


def observe_verify_duration(seconds: float) -> None:
    global _verify_total_seconds, _verify_count
    vellum_verify_duration_seconds.observe(seconds)
    with _METRIC_LOCK:
        _verify_total_seconds += seconds
        _verify_count += 1


def set_native_baseline(seconds: float) -> None:
    global _native_baseline_seconds
    vellum_native_verify_duration_seconds.set(seconds)
    with _METRIC_LOCK:
        _native_baseline_seconds = seconds


def trust_speed_snapshot() -> dict[str, float | None]:
    with _METRIC_LOCK:
        avg_verify_seconds = (
            _verify_total_seconds / _verify_count if _verify_count > 0 else None
        )
        native_seconds = _native_baseline_seconds if _native_baseline_seconds > 0 else None

    if avg_verify_seconds is None or native_seconds is None or avg_verify_seconds <= 0:
        return {
            "native_verify_ms": native_seconds * 1000.0 if native_seconds is not None else None,
            "zk_batch_verify_ms": avg_verify_seconds * 1000.0 if avg_verify_seconds is not None else None,
            "trust_speedup": None,
        }

    return {
        "native_verify_ms": native_seconds * 1000.0,
        "zk_batch_verify_ms": avg_verify_seconds * 1000.0,
        "trust_speedup": native_seconds / avg_verify_seconds,
    }


def prometheus_payload() -> tuple[bytes, str]:
    return generate_latest(), CONTENT_TYPE_LATEST
