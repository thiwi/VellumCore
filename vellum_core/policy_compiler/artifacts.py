"""Compiler artifact and metadata models."""

from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True)
class CompilerArtifacts:
    """Generated source artifacts and deterministic spec hash."""

    spec_hash: str
    python_source: str
    circom_source: str
    debug_trace_source: str


@dataclass(frozen=True)
class CompilerMetadata:
    """Manifest metadata describing one generated artifact set."""

    spec_version: str
    compiler_version: str
    generated_from_hash: str
    generated_python_path: str
    generated_circom_path: str
    generated_debug_trace_path: str

    def as_dict(self) -> dict[str, str]:
        """Serialize metadata for JSON manifest embedding."""
        return {
            "spec_version": self.spec_version,
            "compiler_version": self.compiler_version,
            "generated_from_hash": self.generated_from_hash,
            "generated_python_path": self.generated_python_path,
            "generated_circom_path": self.generated_circom_path,
            "generated_debug_trace_path": self.generated_debug_trace_path,
        }
