"""Tests for Runtime defaults."""

from __future__ import annotations

import asyncio
import importlib
import json
import sys
import types
from pathlib import Path

import pytest

from vellum_core.config import Settings
from vellum_core.registry import CircuitRegistry
from vellum_core.runtime import defaults


def _write_manifest(circuits_dir: Path, *, circuit_id: str) -> None:
    circuit_dir = circuits_dir / circuit_id
    circuit_dir.mkdir(parents=True, exist_ok=True)
    (circuit_dir / "manifest.json").write_text(
        json.dumps(
            {
                "circuit_id": circuit_id,
                "input_schema": {"type": "object"},
                "public_signals": ["ok"],
                "version": "1.0.0",
            }
        ),
        encoding="utf-8",
    )
    (circuit_dir / f"{circuit_id}.circom").write_text("component main {}", encoding="utf-8")


def _make_settings(
    tmp_path: Path,
    *,
    proof_provider_mode: str = "snarkjs",
    proof_shadow_mode: bool = False,
    proof_shadow_provider_mode: str = "grpc",
) -> Settings:
    return Settings(
        app_name="vellum-core",
        circuits_dir=tmp_path / "circuits",
        policy_packs_dir=tmp_path / "policy_packs",
        shared_assets_dir=tmp_path / "shared_assets",
        proof_output_dir=tmp_path / "proofs",
        snarkjs_bin="snarkjs",
        database_url="sqlite:///dummy.db",
        celery_broker_url="redis://localhost:6379/0",
        celery_queue="vellum-queue",
        redis_url="redis://localhost:6379/1",
        vault_addr="https://vault.local",
        vault_token="token",
        vault_jwt_key="vellum-jwt",
        vault_audit_key="vellum-audit",
        vault_bank_key="vellum-bank",
        bank_key_id="bank-key-1",
        bank_key_mapping={"bank-key-1": "vellum-bank"},
        vault_public_key_cache_ttl_seconds=60,
        jwt_issuer="bank.local",
        jwt_audience="sentinel-zk",
        nonce_window_seconds=300,
        jwt_max_ttl_seconds=900,
        jwt_leeway_seconds=30,
        max_parallel_proofs=2,
        submit_rate_limit_per_minute=30,
        max_submit_body_bytes=1_048_576,
        celery_task_soft_time_limit_seconds=50,
        celery_task_time_limit_seconds=60,
        celery_worker_max_tasks_per_child=100,
        proof_job_max_attempts=3,
        security_profile="strict",
        metrics_require_auth=True,
        vellum_data_key="vellum-data",
        tls_ca_bundle=None,
        worker_metrics_host="127.0.0.1",
        worker_metrics_port=9108,
        native_verify_baseline_seconds=0.000005,
        proof_provider_mode=proof_provider_mode,
        grpc_prover_endpoint="127.0.0.1:50051",
        grpc_prover_timeout_seconds=30.0,
        proof_shadow_mode=proof_shadow_mode,
        proof_shadow_provider_mode=proof_shadow_provider_mode,
        proof_shadow_compare_public_signals=True,
    )


def test_filesystem_artifact_store_roundtrip(tmp_path: Path) -> None:
    settings = _make_settings(tmp_path)
    _write_manifest(settings.circuits_dir, circuit_id="batch_credit_check")
    registry = CircuitRegistry(settings.circuits_dir, settings.shared_assets_dir)
    store = defaults.FilesystemArtifactStore(registry)

    artifact_dir = settings.shared_assets_dir / "batch_credit_check"
    artifact_dir.mkdir(parents=True, exist_ok=True)
    wasm = artifact_dir / "batch_credit_check.wasm"
    zkey = artifact_dir / "final.zkey"
    vk = artifact_dir / "verification_key.json"
    for path in (wasm, zkey, vk):
        path.write_text("x", encoding="utf-8")

    view = store.get_artifact_paths("batch_credit_check")
    assert view.circuit_id == "batch_credit_check"
    assert view.wasm_path.endswith("batch_credit_check.wasm")
    assert store.artifacts_exist("batch_credit_check") is True

    vk.unlink()
    assert store.artifacts_exist("batch_credit_check") is False


def test_vault_signer_uses_encoded_signature() -> None:
    class _Signed:
        encoded = "vault:v1:abc"

    class _Client:
        async def sign(self, key_name: str, payload: bytes) -> _Signed:
            assert key_name == "vellum-audit"
            assert payload == b"hello"
            return _Signed()

    signer = defaults.VaultSigner(_Client())  # type: ignore[arg-type]
    assert asyncio.run(signer.sign("vellum-audit", b"hello")) == "vault:v1:abc"


def test_celery_job_backend_calls_send_task(monkeypatch: pytest.MonkeyPatch) -> None:
    recorded: dict[str, object] = {}

    def _fake_send_task(*, task_name: str, args: list[object], queue: str) -> None:
        recorded.update({"task_name": task_name, "args": args, "queue": queue})

    monkeypatch.setattr(defaults, "_send_task", _fake_send_task)
    backend = defaults.CeleryJobBackend()
    asyncio.run(backend.enqueue("worker.process_proof_job", ["p1"], "vellum-queue"))
    assert recorded == {
        "task_name": "worker.process_proof_job",
        "args": ["p1"],
        "queue": "vellum-queue",
    }


def test_send_task_imports_celery_app(monkeypatch: pytest.MonkeyPatch) -> None:
    calls: dict[str, object] = {}

    class _FakeCelery:
        def send_task(self, task_name: str, *, args: list[object], queue: str) -> None:
            calls.update({"task_name": task_name, "args": args, "queue": queue})

    fake_module = types.ModuleType("vellum_core.celery_app")
    fake_module.celery_app = _FakeCelery()  # type: ignore[attr-defined]
    monkeypatch.setitem(sys.modules, "vellum_core.celery_app", fake_module)

    defaults._send_task(task_name="worker.process_proof_job", args=["abc"], queue="q")
    assert calls == {"task_name": "worker.process_proof_job", "args": ["abc"], "queue": "q"}


def test_build_framework_client_wires_dependencies(tmp_path: Path) -> None:
    settings = _make_settings(tmp_path)
    _write_manifest(settings.circuits_dir, circuit_id="batch_credit_check")
    client = defaults.build_framework_client(settings)
    assert client.config.app_name == "vellum-core"
    assert client.config.celery_queue == "vellum-queue"
    assert isinstance(client.provider, defaults.SnarkJSProvider)
    assert isinstance(client.artifact_store, defaults.FilesystemArtifactStore)
    assert isinstance(client.signer, defaults.VaultSigner)
    assert isinstance(client.evidence_store, defaults.FilesystemEvidenceStore)
    assert isinstance(client.attestation_signer, defaults.VaultAttestationSigner)
    assert isinstance(client.job_backend, defaults.CeleryJobBackend)


def test_build_provider_uses_grpc_mode(tmp_path: Path) -> None:
    settings = _make_settings(tmp_path, proof_provider_mode="grpc")
    _write_manifest(settings.circuits_dir, circuit_id="batch_credit_check")
    registry = CircuitRegistry(settings.circuits_dir, settings.shared_assets_dir)
    provider = defaults._build_provider(settings=settings, registry=registry)
    assert isinstance(provider, defaults.GrpcProofProvider)


def test_build_provider_wraps_shadow_mode(tmp_path: Path) -> None:
    settings = _make_settings(
        tmp_path,
        proof_provider_mode="snarkjs",
        proof_shadow_mode=True,
        proof_shadow_provider_mode="grpc",
    )
    _write_manifest(settings.circuits_dir, circuit_id="batch_credit_check")
    registry = CircuitRegistry(settings.circuits_dir, settings.shared_assets_dir)
    provider = defaults._build_provider(settings=settings, registry=registry)
    assert isinstance(provider, defaults.ShadowProofProvider)
    assert isinstance(provider.primary, defaults.SnarkJSProvider)
    assert isinstance(provider.shadow, defaults.GrpcProofProvider)


def test_celery_app_module_builds_queue(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("SECURITY_PROFILE", "dev")
    monkeypatch.setenv("VELLUM_DATA_KEY", "vellum-data")
    monkeypatch.setenv("CELERY_QUEUE", "test-q")

    class _Conf(dict):
        def update(self, **kwargs: object) -> None:  # type: ignore[override]
            super().update(kwargs)

        def __getattr__(self, name: str) -> object:
            return self[name]

    class _FakeCelery:
        def __init__(self, _name: str, *, broker: str, backend: object) -> None:
            self.broker = broker
            self.backend = backend
            self.conf = _Conf()

    fake_celery_module = types.ModuleType("celery")
    fake_celery_module.Celery = _FakeCelery  # type: ignore[attr-defined]
    monkeypatch.setitem(sys.modules, "celery", fake_celery_module)

    module = importlib.import_module("vellum_core.celery_app")
    module = importlib.reload(module)
    assert module.celery_app.conf.task_default_queue == "test-q"
    routes = module.celery_app.conf.task_routes
    assert routes["worker.process_proof_job"]["queue"] == "test-q"
    assert module.celery_app.conf.task_soft_time_limit == 50
    assert module.celery_app.conf.task_time_limit == 60
    assert module.celery_app.conf.task_acks_late is True
    assert module.celery_app.conf.task_reject_on_worker_lost is True
    assert module.celery_app.conf.worker_prefetch_multiplier == 1
    assert module.celery_app.conf.worker_max_tasks_per_child == 100
