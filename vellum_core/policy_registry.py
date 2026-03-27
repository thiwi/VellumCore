"""Policy-pack discovery and manifest access for compliance policy runs."""

from __future__ import annotations

import json
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from pydantic import BaseModel, ConfigDict, Field, ValidationError

from vellum_core.policies.primitives import unknown_primitives


class PolicyNotFoundError(Exception):
    """Raised when a policy id is requested but not present in registry."""


class PolicyManifestError(Exception):
    """Raised when a policy manifest is invalid during discovery."""


class DifferentialOutputSpec(BaseModel):
    """Manifest spec describing one public output checked in differential mode."""

    model_config = ConfigDict(extra="forbid")

    signal_index: int = Field(ge=0)
    value_type: str = Field(pattern="^(int|bool|string)$")


class PolicyPackManifest(BaseModel):
    """Declarative manifest describing one policy pack."""

    model_config = ConfigDict(extra="forbid")

    policy_id: str = Field(min_length=1)
    policy_version: str = Field(min_length=1)
    circuit_id: str = Field(min_length=1)
    description: str | None = None
    input_contract: dict[str, Any] = Field(default_factory=dict)
    evidence_contract: dict[str, Any] = Field(default_factory=dict)
    reference_policy: str = Field(min_length=1)
    primitives: list[str] = Field(min_length=1)
    differential_outputs: dict[str, DifferentialOutputSpec] = Field(min_length=1)
    expected_attestation: dict[str, Any] = Field(default_factory=dict)


@dataclass(frozen=True)
class PolicyPackPaths:
    """Filesystem locations used by one policy pack."""

    policy_dir: Path
    manifest_path: Path


class PolicyRegistry:
    """Discovers policy packs and exposes validated manifests."""

    def __init__(self, policy_packs_dir: Path) -> None:
        self.policy_packs_dir = policy_packs_dir
        self._manifests: dict[str, PolicyPackManifest] = {}
        self.refresh()

    def refresh(self) -> None:
        """Reload policy-pack manifests from disk."""
        self._manifests.clear()
        if not self.policy_packs_dir.exists():
            return

        for candidate in self.policy_packs_dir.iterdir():
            if not candidate.is_dir():
                continue
            manifest_path = candidate / "manifest.json"
            if not manifest_path.exists():
                continue
            try:
                raw_manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
                manifest = PolicyPackManifest.model_validate(raw_manifest)
            except (json.JSONDecodeError, ValidationError) as exc:
                raise PolicyManifestError(
                    f"policy_manifest_invalid: {manifest_path}: {exc}"
                ) from exc
            unknown = unknown_primitives(manifest.primitives)
            if unknown:
                raise PolicyManifestError(
                    f"policy_manifest_invalid: {manifest_path}: unknown primitives {unknown}"
                )
            self._manifests[manifest.policy_id] = manifest

    def list_policies(self) -> list[str]:
        """Return sorted discovered policy identifiers."""
        return sorted(self._manifests.keys())

    def get_manifest(self, policy_id: str) -> PolicyPackManifest:
        """Return validated manifest for a policy id."""
        manifest = self._manifests.get(policy_id)
        if manifest is None:
            raise PolicyNotFoundError(policy_id)
        return manifest

    def get_paths(self, policy_id: str) -> PolicyPackPaths:
        """Return policy pack paths for one policy id."""
        manifest = self.get_manifest(policy_id)
        policy_dir = self.policy_packs_dir / manifest.policy_id
        return PolicyPackPaths(policy_dir=policy_dir, manifest_path=policy_dir / "manifest.json")
