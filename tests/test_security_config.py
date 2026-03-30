"""Tests for Security config."""

from __future__ import annotations

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
    monkeypatch.setenv("PROOF_SHADOW_MODE", "true")
    with pytest.raises(ValueError, match="PROOF_SHADOW_MODE"):
        Settings.from_env()


def test_invalid_shadow_provider_mode_rejected(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("SECURITY_PROFILE", "dev")
    monkeypatch.setenv("VELLUM_DATA_KEY", "vellum-data")
    monkeypatch.setenv("PROOF_SHADOW_PROVIDER_MODE", "snarkjs")
    with pytest.raises(ValueError, match="PROOF_SHADOW_PROVIDER_MODE"):
        Settings.from_env()


def test_non_grpc_mode_rejected(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("SECURITY_PROFILE", "dev")
    monkeypatch.setenv("VELLUM_DATA_KEY", "vellum-data")
    monkeypatch.setenv("PROOF_PROVIDER_MODE", "snarkjs")
    with pytest.raises(ValueError, match="PROOF_PROVIDER_MODE must be grpc"):
        Settings.from_env()
