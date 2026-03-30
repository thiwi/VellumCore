"""Default runtime wiring for providers, adapters, signers, and job backend."""

from __future__ import annotations

import asyncio
import json
from pathlib import Path
from typing import Any

from vellum_core.api import (
    AttestationService,
    CircuitManager,
    FrameworkClient,
    FrameworkConfig,
    PolicyEngine,
    ProofEngine,
)
from vellum_core.config import Settings
from vellum_core.policy_registry import PolicyRegistry
from vellum_core.providers import (
    GrpcProofProvider,
    ShadowProofProvider,
    SnarkJSProvider,
    ZKProvider,
)
from vellum_core.registry import CircuitRegistry
from vellum_core.spi import (
    ArtifactPathsView,
    ArtifactStore,
    AttestationSigner,
    EvidenceStore,
    JobBackend,
    Signer,
)
from vellum_core.vault import VaultTransitClient
from vellum_core.runtime.proof_provider_config import ProofProviderRuntimeConfig
from vellum_core.runtime.proof_provider_factory import build_proof_provider

_PROVIDER_TYPES = (SnarkJSProvider, GrpcProofProvider, ShadowProofProvider)


class FilesystemArtifactStore(ArtifactStore):
    """ArtifactStore backed by local/shared filesystem layout."""

    def __init__(self, registry: CircuitRegistry) -> None:
        self.registry = registry

    def get_artifact_paths(self, circuit_id: str) -> ArtifactPathsView:
        paths = self.registry.get_artifact_paths(circuit_id)
        return ArtifactPathsView(
            circuit_id=circuit_id,
            wasm_path=str(paths.wasm_path),
            zkey_path=str(paths.zkey_path),
            verification_key_path=str(paths.verification_key_path),
        )

    def artifacts_exist(self, circuit_id: str) -> bool:
        paths = self.registry.get_artifact_paths(circuit_id)
        return all(
            p.exists() for p in (paths.wasm_path, paths.zkey_path, paths.verification_key_path)
        )


class FilesystemEvidenceStore(EvidenceStore):
    """EvidenceStore implementation backed by JSON files on local disk."""

    def __init__(self, base_dir: Path) -> None:
        self.base_dir = base_dir

    async def put(self, *, run_id: str, payload: dict[str, Any]) -> str:
        self.base_dir.mkdir(parents=True, exist_ok=True)
        path = self.base_dir / f"{run_id}.json"
        await asyncio.to_thread(
            path.write_text,
            json.dumps(payload, sort_keys=True, separators=(",", ":")),
            "utf-8",
        )
        return str(path)

    async def get(self, *, reference: str) -> dict[str, Any]:
        path = Path(reference)
        if not path.exists():
            raise FileNotFoundError(f"evidence reference does not exist: {reference}")
        raw = await asyncio.to_thread(path.read_text, "utf-8")
        data = json.loads(raw)
        if not isinstance(data, dict):
            raise ValueError("evidence payload must be a JSON object")
        return data


class VaultSigner(Signer):
    """Signer implementation delegating to Vault Transit."""

    def __init__(self, client: VaultTransitClient) -> None:
        self.client = client

    async def sign(self, key_name: str, payload: bytes) -> str:
        signature = await self.client.sign(key_name, payload)
        return signature.encoded


class VaultAttestationSigner(AttestationSigner):
    """Attestation signer that uses the configured generic Signer backend."""

    def __init__(self, *, signer: Signer, key_name: str) -> None:
        self.signer = signer
        self.key_name = key_name

    async def sign_attestation(self, payload: bytes) -> str:
        return await self.signer.sign(self.key_name, payload)


class CeleryJobBackend(JobBackend):
    """Job backend implementation using Celery task dispatch."""

    async def enqueue(self, task_name: str, args: list[Any], queue: str) -> None:
        _send_task(task_name=task_name, args=args, queue=queue)


def _send_task(*, task_name: str, args: list[Any], queue: str) -> None:
    """Import-and-send Celery task lazily to avoid startup side effects."""
    from vellum_core.celery_app import celery_app

    celery_app.send_task(task_name, args=args, queue=queue)


def build_framework_client(settings: Settings) -> FrameworkClient:
    """Build the default production-style framework composition."""
    registry = CircuitRegistry(settings.circuits_dir, settings.shared_assets_dir)
    artifact_store = FilesystemArtifactStore(registry)
    provider = _build_provider(settings=settings, registry=registry)
    circuit_manager = CircuitManager(registry=registry, artifact_store=artifact_store)
    proof_engine = ProofEngine(provider=provider, circuit_manager=circuit_manager)
    policy_registry = PolicyRegistry(settings.policy_packs_dir)
    evidence_store = FilesystemEvidenceStore(settings.proof_output_dir / "evidence")
    vault_client = VaultTransitClient(
        addr=settings.vault_addr,
        token=settings.vault_token,
        tls_ca_bundle=settings.tls_ca_bundle,
    )
    signer = VaultSigner(vault_client)
    attestation_signer = VaultAttestationSigner(
        signer=signer,
        key_name=settings.vault_audit_key,
    )
    attestation_service = AttestationService(
        artifact_store=artifact_store,
        signer=attestation_signer,
    )
    policy_engine = PolicyEngine(
        proof_engine=proof_engine,
        policy_registry=policy_registry,
        evidence_store=evidence_store,
        attestation_service=attestation_service,
    )

    return FrameworkClient(
        config=FrameworkConfig.from_settings(settings),
        circuit_manager=circuit_manager,
        proof_engine=proof_engine,
        policy_engine=policy_engine,
        attestation_service=attestation_service,
        policy_registry=policy_registry,
        provider=provider,
        artifact_store=artifact_store,
        signer=signer,
        evidence_store=evidence_store,
        attestation_signer=attestation_signer,
        job_backend=CeleryJobBackend(),
    )


def _build_provider(*, settings: Settings, registry: CircuitRegistry) -> ZKProvider:
    """Build primary provider and optional shadow wrapper from settings."""
    runtime_config = ProofProviderRuntimeConfig.from_settings(settings)
    return build_proof_provider(
        registry=registry,
        config=runtime_config,
    )
