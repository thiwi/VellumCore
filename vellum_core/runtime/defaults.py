"""Default runtime wiring for providers, adapters, signers, and job backend."""

from __future__ import annotations

from typing import Any

from vellum_core.api import CircuitManager, FrameworkClient, FrameworkConfig, ProofEngine
from vellum_core.config import Settings
from vellum_core.providers import SnarkJSProvider
from vellum_core.registry import CircuitRegistry
from vellum_core.spi import ArtifactPathsView, ArtifactStore, JobBackend, Signer
from vellum_core.vault import VaultTransitClient


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


class VaultSigner(Signer):
    """Signer implementation delegating to Vault Transit."""

    def __init__(self, client: VaultTransitClient) -> None:
        self.client = client

    async def sign(self, key_name: str, payload: bytes) -> str:
        signature = await self.client.sign(key_name, payload)
        return signature.encoded


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
    provider = SnarkJSProvider(registry=registry, snarkjs_bin=settings.snarkjs_bin)
    circuit_manager = CircuitManager(registry=registry, artifact_store=artifact_store)
    proof_engine = ProofEngine(provider=provider, circuit_manager=circuit_manager)
    vault_client = VaultTransitClient(
        addr=settings.vault_addr,
        token=settings.vault_token,
        tls_ca_bundle=settings.tls_ca_bundle,
    )

    return FrameworkClient(
        config=FrameworkConfig.from_settings(settings),
        circuit_manager=circuit_manager,
        proof_engine=proof_engine,
        provider=provider,
        artifact_store=artifact_store,
        signer=VaultSigner(vault_client),
        job_backend=CeleryJobBackend(),
    )
