"""Tests for Security config."""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from vellum_core.config import Settings


def test_settings_require_data_key(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.delenv("VELLUM_DATA_KEY", raising=False)
    monkeypatch.setenv("SECURITY_PROFILE", "dev")
    with pytest.raises(ValueError, match="VELLUM_DATA_KEY is required"):
        Settings.from_env()


def test_strict_profile_rejects_insecure_defaults(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("SECURITY_PROFILE", "strict")
    monkeypatch.setenv("VELLUM_DATA_KEY", "vellum-data")
    monkeypatch.setenv("VAULT_TOKEN", "root")
    monkeypatch.setenv("VAULT_ADDR", "http://vault:8200")
    with pytest.raises(ValueError, match="VAULT_TOKEN"):
        Settings.from_env()


def test_dev_profile_allows_local_defaults(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("SECURITY_PROFILE", "dev")
    monkeypatch.setenv("VELLUM_DATA_KEY", "vellum-data")
    monkeypatch.setenv("VAULT_TOKEN", "root")
    monkeypatch.setenv("VAULT_ADDR", "http://vault:8200")
    settings = Settings.from_env()
    assert settings.security_profile == "dev"


def test_invalid_proof_provider_mode_rejected(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("SECURITY_PROFILE", "dev")
    monkeypatch.setenv("VELLUM_DATA_KEY", "vellum-data")
    monkeypatch.setenv("PROOF_PROVIDER_MODE", "invalid")
    with pytest.raises(ValueError, match="PROOF_PROVIDER_MODE"):
        Settings.from_env()


def test_invalid_shadow_mode_rejected(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("SECURITY_PROFILE", "dev")
    monkeypatch.setenv("VELLUM_DATA_KEY", "vellum-data")
    monkeypatch.setenv("PROOF_SHADOW_PROVIDER_MODE", "invalid")
    with pytest.raises(ValueError, match="PROOF_SHADOW_PROVIDER_MODE"):
        Settings.from_env()


def test_grpc_mode_with_enforced_gate_requires_report_path(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("SECURITY_PROFILE", "dev")
    monkeypatch.setenv("VELLUM_DATA_KEY", "vellum-data")
    monkeypatch.setenv("PROOF_PROVIDER_MODE", "grpc")
    monkeypatch.setenv("GRPC_CUTOVER_GATE_ENFORCED", "true")
    monkeypatch.delenv("GRPC_CUTOVER_GATE_REPORT_PATH", raising=False)
    with pytest.raises(ValueError, match="GRPC_CUTOVER_GATE_REPORT_PATH"):
        Settings.from_env()


def test_grpc_mode_with_enforced_gate_rejects_failing_report(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    report = tmp_path / "gate.json"
    report.write_text(json.dumps({"result": {"pass_gate": False}}), encoding="utf-8")
    monkeypatch.setenv("SECURITY_PROFILE", "dev")
    monkeypatch.setenv("VELLUM_DATA_KEY", "vellum-data")
    monkeypatch.setenv("PROOF_PROVIDER_MODE", "grpc")
    monkeypatch.setenv("GRPC_CUTOVER_GATE_ENFORCED", "true")
    monkeypatch.setenv("GRPC_CUTOVER_GATE_REPORT_PATH", str(report))
    with pytest.raises(ValueError, match="did not pass"):
        Settings.from_env()


def test_grpc_mode_with_enforced_gate_accepts_passing_report(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    report = tmp_path / "gate.json"
    report.write_text(json.dumps({"pass_gate": True}), encoding="utf-8")
    monkeypatch.setenv("SECURITY_PROFILE", "dev")
    monkeypatch.setenv("VELLUM_DATA_KEY", "vellum-data")
    monkeypatch.setenv("PROOF_PROVIDER_MODE", "grpc")
    monkeypatch.setenv("GRPC_CUTOVER_GATE_ENFORCED", "true")
    monkeypatch.setenv("GRPC_CUTOVER_GATE_REPORT_PATH", str(report))
    settings = Settings.from_env()
    assert settings.proof_provider_mode == "grpc"
