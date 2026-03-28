"""Framework-facing configuration model projected from runtime settings."""

from __future__ import annotations

from pathlib import Path

from pydantic import BaseModel, ConfigDict

from vellum_core.config import Settings


class FrameworkConfig(BaseModel):
    """Serializable framework runtime configuration exposed through the API layer."""

    model_config = ConfigDict(extra="forbid")

    app_name: str
    circuits_dir: Path
    policy_packs_dir: Path
    shared_assets_dir: Path
    proof_output_dir: Path
    snarkjs_bin: str
    proof_provider_mode: str
    grpc_prover_endpoint: str
    proof_shadow_mode: bool
    proof_shadow_provider_mode: str
    grpc_cutover_gate_enforced: bool
    grpc_cutover_gate_report_path: str | None
    database_url: str
    celery_queue: str
    native_verify_baseline_seconds: float

    @classmethod
    def from_settings(cls, settings: Settings) -> "FrameworkConfig":
        """Project internal settings to the framework-facing config model."""
        return cls(
            app_name=settings.app_name,
            circuits_dir=settings.circuits_dir,
            policy_packs_dir=settings.policy_packs_dir,
            shared_assets_dir=settings.shared_assets_dir,
            proof_output_dir=settings.proof_output_dir,
            snarkjs_bin=settings.snarkjs_bin,
            proof_provider_mode=settings.proof_provider_mode,
            grpc_prover_endpoint=settings.grpc_prover_endpoint,
            proof_shadow_mode=settings.proof_shadow_mode,
            proof_shadow_provider_mode=settings.proof_shadow_provider_mode,
            grpc_cutover_gate_enforced=settings.grpc_cutover_gate_enforced,
            grpc_cutover_gate_report_path=settings.grpc_cutover_gate_report_path,
            database_url=settings.database_url,
            celery_queue=settings.celery_queue,
            native_verify_baseline_seconds=settings.native_verify_baseline_seconds,
        )

    @classmethod
    def from_env(cls) -> "FrameworkConfig":
        """Build configuration directly from environment variables."""
        return cls.from_settings(Settings.from_env())
