"""Attestation bundle construction and export helpers."""

from __future__ import annotations

import hashlib
import json
from pathlib import Path
from typing import Any

from vellum_core.api.errors import framework_error
from vellum_core.api.types import AttestationBundle
from vellum_core.spi import ArtifactStore, AttestationSigner


class AttestationService:
    """Creates signed attestation bundles and exports them by id."""

    def __init__(
        self,
        *,
        artifact_store: ArtifactStore,
        signer: AttestationSigner,
    ) -> None:
        self.artifact_store = artifact_store
        self.signer = signer
        self._bundles: dict[str, AttestationBundle] = {}

    async def create(
        self,
        *,
        attestation_id: str,
        run_id: str,
        policy_id: str,
        policy_version: str,
        circuit_id: str,
        decision: str,
        proof: dict[str, Any],
        public_signals: list[Any],
        metadata: dict[str, Any] | None = None,
    ) -> AttestationBundle:
        """Build and persist one bundle from proof artifacts and metadata."""
        proof_hash = _sha256_json(proof)
        public_signals_hash = _sha256_json(public_signals)
        artifact_digests = self._artifact_digests(circuit_id)
        signature_chain: list[dict[str, Any]] = []

        unsigned = {
            "attestation_id": attestation_id,
            "run_id": run_id,
            "policy_id": policy_id,
            "policy_version": policy_version,
            "circuit_id": circuit_id,
            "decision": decision,
            "proof_hash": proof_hash,
            "public_signals_hash": public_signals_hash,
            "artifact_digests": artifact_digests,
            "metadata": metadata or {},
        }
        signature = await self.signer.sign_attestation(
            json.dumps(unsigned, sort_keys=True, separators=(",", ":")).encode("utf-8")
        )
        signature_chain.append(
            {
                "type": "attestation_bundle_signature",
                "signature": signature,
            }
        )

        bundle = AttestationBundle.create(
            attestation_id=attestation_id,
            run_id=run_id,
            policy_id=policy_id,
            policy_version=policy_version,
            circuit_id=circuit_id,
            decision="pass" if decision == "pass" else "fail",
            proof_hash=proof_hash,
            public_signals_hash=public_signals_hash,
            artifact_digests=artifact_digests,
            signature_chain=signature_chain,
            metadata=metadata,
        )
        self._bundles[attestation_id] = bundle
        return bundle

    async def export(self, attestation_id: str) -> AttestationBundle:
        """Return one previously generated attestation bundle."""
        bundle = self._bundles.get(attestation_id)
        if bundle is None:
            raise framework_error(
                "unknown_attestation_id",
                "Attestation id not found",
                attestation_id=attestation_id,
            )
        return bundle

    def _artifact_digests(self, circuit_id: str) -> dict[str, str]:
        paths = self.artifact_store.get_artifact_paths(circuit_id)
        return {
            "wasm_sha256": _sha256_file(paths.wasm_path),
            "zkey_sha256": _sha256_file(paths.zkey_path),
            "verification_key_sha256": _sha256_file(paths.verification_key_path),
        }


def _sha256_json(payload: Any) -> str:
    return hashlib.sha256(
        json.dumps(payload, sort_keys=True, separators=(",", ":")).encode("utf-8")
    ).hexdigest()


def _sha256_file(path_value: str) -> str:
    path = Path(path_value)
    if not path.exists() or not path.is_file():
        return ""
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(8192), b""):
            digest.update(chunk)
    return digest.hexdigest()
