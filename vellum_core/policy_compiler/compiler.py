"""Compatibility facade for policy compiler helpers.

Internal implementation is split across focused modules:
- spec loading/validation
- Python/Circom renderers
- manifest metadata synchronization
- drift detection
"""

from __future__ import annotations

import hashlib
import json

from vellum_core.policy_compiler.artifacts import CompilerArtifacts, CompilerMetadata
from vellum_core.policy_compiler.circom_renderer import render_circom_source
from vellum_core.policy_compiler.drift import check_drift, write_generated_artifacts
from vellum_core.policy_compiler.manifest import (
    build_compiler_metadata,
    sync_manifest_compiler_metadata,
)
from vellum_core.policy_compiler.models import PolicyDSLSpec
from vellum_core.policy_compiler.python_renderer import render_python_source
from vellum_core.policy_compiler.spec_loader import load_policy_spec
from vellum_core.policy_compiler.validation import ensure_supported_decision


def generate_policy_artifacts(spec: PolicyDSLSpec) -> CompilerArtifacts:
    """Generate deterministic Python and Circom sources for one DSL spec."""
    ensure_supported_decision(spec)
    canonical = json.dumps(spec.model_dump(mode="json"), sort_keys=True, separators=(",", ":"))
    spec_hash = hashlib.sha256(canonical.encode("utf-8")).hexdigest()
    python_source = render_python_source(spec, spec_hash=spec_hash)
    circom_source = render_circom_source(spec, spec_hash=spec_hash)
    return CompilerArtifacts(
        spec_hash=spec_hash,
        python_source=python_source,
        circom_source=circom_source,
    )


__all__ = [
    "CompilerArtifacts",
    "CompilerMetadata",
    "build_compiler_metadata",
    "check_drift",
    "generate_policy_artifacts",
    "load_policy_spec",
    "sync_manifest_compiler_metadata",
    "write_generated_artifacts",
]
