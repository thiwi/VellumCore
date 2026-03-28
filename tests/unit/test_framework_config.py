"""Tests for Framework config."""

from __future__ import annotations

from pathlib import Path

import pytest

from vellum_core.api.config import FrameworkConfig
from vellum_core.config import Settings


def test_framework_config_from_settings(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("SECURITY_PROFILE", "dev")
    monkeypatch.setenv("VELLUM_DATA_KEY", "vellum-data")
    monkeypatch.setenv("PROOF_PROVIDER_MODE", "grpc")
    monkeypatch.setenv("GRPC_PROVER_ENDPOINT", "localhost:50052")
    monkeypatch.setenv("PROOF_SHADOW_MODE", "true")
    monkeypatch.setenv("PROOF_SHADOW_PROVIDER_MODE", "snarkjs")
    settings = Settings.from_env()
    cfg = FrameworkConfig.from_settings(settings)
    assert cfg.app_name == settings.app_name
    assert cfg.circuits_dir == Path(settings.circuits_dir)
    assert cfg.policy_packs_dir == Path(settings.policy_packs_dir)
    assert cfg.shared_assets_dir == Path(settings.shared_assets_dir)
    assert cfg.celery_queue == settings.celery_queue
    assert cfg.proof_provider_mode == "grpc"
    assert cfg.grpc_prover_endpoint == "localhost:50052"
    assert cfg.proof_shadow_mode is True
    assert cfg.proof_shadow_provider_mode == "snarkjs"
