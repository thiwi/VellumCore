"""Tests for Framework config."""

from __future__ import annotations

from pathlib import Path

import pytest

from vellum_core.api.config import FrameworkConfig
from vellum_core.config import Settings


def test_framework_config_from_settings(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("SECURITY_PROFILE", "dev")
    monkeypatch.setenv("VELLUM_DATA_KEY", "vellum-data")
    settings = Settings.from_env()
    cfg = FrameworkConfig.from_settings(settings)
    assert cfg.app_name == settings.app_name
    assert cfg.circuits_dir == Path(settings.circuits_dir)
    assert cfg.policy_packs_dir == Path(settings.policy_packs_dir)
    assert cfg.shared_assets_dir == Path(settings.shared_assets_dir)
    assert cfg.celery_queue == settings.celery_queue
