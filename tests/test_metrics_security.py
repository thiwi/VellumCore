"""Tests for Metrics security."""

from __future__ import annotations

from vellum_core import metrics


def test_trust_speed_snapshot_with_no_verify_samples() -> None:
    metrics.set_native_baseline(0.001)
    snapshot = metrics.trust_speed_snapshot()
    assert snapshot["native_verify_ms"] == 1.0
    assert snapshot["trust_speedup"] is None


def test_observe_verify_and_security_metrics_present_in_payload() -> None:
    metrics.observe_verify_duration(0.002)
    metrics.observe_security_event("jwt_invalid", "denied")
    metrics.observe_shadow_event("verify", "mismatch")
    payload, _ = metrics.prometheus_payload()
    text = payload.decode("utf-8")
    assert "vellum_verify_duration_seconds" in text
    assert "vellum_security_events_total" in text
    assert "vellum_proof_shadow_events_total" in text
