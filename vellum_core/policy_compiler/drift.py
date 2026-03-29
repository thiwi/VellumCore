"""Artifact persistence and drift-check logic for compiler outputs."""

from __future__ import annotations

from pathlib import Path

from vellum_core.policy_compiler.artifacts import CompilerArtifacts
from vellum_core.policy_compiler.manifest import build_compiler_metadata, manifest_metadata_matches
from vellum_core.policy_compiler.models import PolicyDSLSpec


def write_generated_artifacts(
    *,
    repo_root: Path,
    spec: PolicyDSLSpec,
    artifacts: CompilerArtifacts,
) -> tuple[Path, Path]:
    """Write generated artifacts to deterministic repo-relative target paths."""
    python_path = repo_root / spec.generated_python_path
    circom_path = repo_root / spec.generated_circom_path
    python_path.parent.mkdir(parents=True, exist_ok=True)
    circom_path.parent.mkdir(parents=True, exist_ok=True)
    python_path.write_text(artifacts.python_source, encoding="utf-8")
    circom_path.write_text(artifacts.circom_source, encoding="utf-8")
    return python_path, circom_path


def check_drift(
    *,
    repo_root: Path,
    spec: PolicyDSLSpec,
    artifacts: CompilerArtifacts,
    manifest_path: Path | None = None,
) -> bool:
    """Return True when generated artifacts are identical to committed files."""
    python_path = repo_root / spec.generated_python_path
    circom_path = repo_root / spec.generated_circom_path
    if not python_path.exists() or not circom_path.exists():
        return False

    committed_python = python_path.read_text(encoding="utf-8")
    committed_circom = circom_path.read_text(encoding="utf-8")
    artifacts_match = (
        committed_python == artifacts.python_source
        and committed_circom == artifacts.circom_source
    )
    if not artifacts_match:
        return False

    if manifest_path is None or not manifest_path.exists():
        return True

    expected = build_compiler_metadata(spec=spec, artifacts=artifacts)
    return manifest_metadata_matches(manifest_path=manifest_path, expected=expected)
