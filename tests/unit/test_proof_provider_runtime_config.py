"""Tests for typed proof-provider runtime configuration and factory."""

from __future__ import annotations

from pathlib import Path

import pytest

from vellum_core.config import Settings
from vellum_core.registry import CircuitRegistry
from vellum_core.runtime.proof_provider_config import ProofProviderRuntimeConfig
from vellum_core.runtime.proof_provider_factory import build_proof_provider


def _settings(tmp_path: Path, **overrides: object) -> Settings:
    base: dict[str, object] = {
        "app_name": "vellum-core",
        "circuits_dir": tmp_path / "circuits",
        "policy_packs_dir": tmp_path / "policy_packs",
        "shared_assets_dir": tmp_path / "shared_assets",
        "proof_output_dir": tmp_path / "proofs",
        "snarkjs_bin": "snarkjs",
        "database_url": "sqlite:///dummy.db",
        "celery_broker_url": "redis://localhost:6379/0",
        "celery_queue": "vellum-queue",
        "redis_url": "redis://localhost:6379/1",
        "vault_addr": "https://vault.local",
        "vault_token": "token",
        "vault_jwt_key": "vellum-jwt",
        "vault_audit_key": "vellum-audit",
        "vault_bank_key": "vellum-bank",
        "bank_key_id": "bank-key-1",
        "bank_key_mapping": {"bank-key-1": "vellum-bank"},
        "vault_public_key_cache_ttl_seconds": 60,
        "jwt_issuer": "bank.local",
        "jwt_audience": "sentinel-zk",
        "nonce_window_seconds": 300,
        "jwt_max_ttl_seconds": 900,
        "jwt_leeway_seconds": 30,
        "max_parallel_proofs": 2,
        "submit_rate_limit_per_minute": 30,
        "max_submit_body_bytes": 1_048_576,
        "celery_task_soft_time_limit_seconds": 50,
        "celery_task_time_limit_seconds": 60,
        "celery_worker_max_tasks_per_child": 100,
        "proof_job_max_attempts": 3,
        "security_profile": "strict",
        "metrics_require_auth": True,
        "vellum_data_key": "vellum-data",
        "tls_ca_bundle": None,
        "worker_metrics_host": "127.0.0.1",
        "worker_metrics_port": 9108,
        "native_verify_baseline_seconds": 0.000005,
        "proof_provider_mode": "snarkjs",
        "grpc_prover_endpoint": "127.0.0.1:50051",
        "grpc_prover_timeout_seconds": 30.0,
        "proof_shadow_mode": False,
        "proof_shadow_provider_mode": "grpc",
        "proof_shadow_compare_public_signals": True,
    }
    base.update(overrides)
    return Settings(**base)


def _write_manifest(circuits_dir: Path, *, circuit_id: str) -> None:
    circuit_dir = circuits_dir / circuit_id
    circuit_dir.mkdir(parents=True, exist_ok=True)
    (circuit_dir / "manifest.json").write_text(
        (
            '{"circuit_id":"'
            + circuit_id
            + '","input_schema":{"type":"object"},"public_signals":["ok"],"version":"1.0.0"}'
        ),
        encoding="utf-8",
    )
    (circuit_dir / f"{circuit_id}.circom").write_text("component main {}", encoding="utf-8")


@pytest.mark.unit
def test_runtime_config_normalizes_from_settings(tmp_path: Path) -> None:
    settings = _settings(
        tmp_path,
        proof_provider_mode="grpc",
        proof_shadow_mode=True,
        proof_shadow_provider_mode="snarkjs",
    )

    runtime = ProofProviderRuntimeConfig.from_settings(settings)
    assert runtime.primary_mode == "grpc"
    assert runtime.shadow_enabled is True
    assert runtime.shadow_mode == "snarkjs"


@pytest.mark.unit
def test_runtime_config_rejects_invalid_grpc_timeout(tmp_path: Path) -> None:
    settings = _settings(tmp_path, grpc_prover_timeout_seconds=0.0)

    with pytest.raises(ValueError, match="GRPC_PROVER_TIMEOUT_SECONDS"):
        ProofProviderRuntimeConfig.from_settings(settings)


@pytest.mark.unit
def test_factory_builds_shadow_provider_when_enabled(tmp_path: Path) -> None:
    _write_manifest(tmp_path / "circuits", circuit_id="batch_credit_check")
    settings = _settings(
        tmp_path,
        proof_provider_mode="snarkjs",
        proof_shadow_mode=True,
        proof_shadow_provider_mode="grpc",
    )
    runtime = ProofProviderRuntimeConfig.from_settings(settings)
    registry = CircuitRegistry(settings.circuits_dir, settings.shared_assets_dir)

    provider = build_proof_provider(
        registry=registry,
        snarkjs_bin=settings.snarkjs_bin,
        config=runtime,
    )
    assert provider.__class__.__name__ == "ShadowProofProvider"
