"""Manifest metadata helpers for generated compiler artifacts."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from vellum_core.policy_compiler.artifacts import CompilerArtifacts, CompilerMetadata
from vellum_core.policy_compiler.models import PolicyDSLSpec


def build_compiler_metadata(*, spec: PolicyDSLSpec, artifacts: CompilerArtifacts) -> CompilerMetadata:
    """Build manifest compiler metadata for one spec/artifact set."""
    return CompilerMetadata(
        spec_version=spec.spec_version,
        compiler_version=spec.compiler_version,
        generated_from_hash=artifacts.spec_hash,
        generated_python_path=spec.generated_python_path,
        generated_circom_path=spec.generated_circom_path,
    )


def sync_manifest_compiler_metadata(*, manifest_path: Path, metadata: CompilerMetadata) -> bool:
    """Update manifest compiler metadata and return True when file changed."""
    if not manifest_path.exists():
        return False

    try:
        manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    except json.JSONDecodeError:
        return False
    if not isinstance(manifest, dict):
        return False

    next_metadata = metadata.as_dict()
    current = manifest.get("compiler_metadata")
    if current == next_metadata:
        return False

    manifest["compiler_metadata"] = next_metadata
    manifest_path.write_text(json.dumps(manifest, indent=2) + "\n", encoding="utf-8")
    return True


def manifest_metadata_matches(*, manifest_path: Path, expected: CompilerMetadata) -> bool:
    """Return whether manifest compiler_metadata matches expected value exactly."""
    try:
        manifest: Any = json.loads(manifest_path.read_text(encoding="utf-8"))
    except json.JSONDecodeError:
        return False
    if not isinstance(manifest, dict):
        return False
    return manifest.get("compiler_metadata") == expected.as_dict()
