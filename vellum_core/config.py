"""Environment-driven runtime settings used across services and framework."""

from __future__ import annotations

import json
import os
from dataclasses import dataclass
from pathlib import Path


@dataclass(frozen=True)
class Settings:
    """Runtime settings model loaded from process environment."""

    app_name: str
    circuits_dir: Path
    shared_assets_dir: Path
    proof_output_dir: Path
    snarkjs_bin: str

    database_url: str
    celery_broker_url: str
    celery_queue: str
    redis_url: str

    vault_addr: str
    vault_token: str
    vault_jwt_key: str
    vault_audit_key: str
    vault_bank_key: str
    bank_key_id: str
    bank_key_mapping: dict[str, str]
    vault_public_key_cache_ttl_seconds: int

    jwt_issuer: str
    jwt_audience: str
    nonce_window_seconds: int
    jwt_max_ttl_seconds: int
    jwt_leeway_seconds: int
    max_parallel_proofs: int
    submit_rate_limit_per_minute: int

    security_profile: str
    metrics_require_auth: bool
    vellum_data_key: str
    tls_ca_bundle: str | None

    worker_metrics_host: str
    worker_metrics_port: int
    native_verify_baseline_seconds: float

    @classmethod
    def from_env(cls) -> "Settings":
        """Build validated settings with defaults suitable for local/dev execution."""
        base_dir = Path(os.getenv("APP_BASE_DIR", Path.cwd()))
        circuits_dir = Path(os.getenv("CIRCUITS_DIR", str(base_dir / "circuits")))
        shared_assets_dir = Path(
            os.getenv("SHARED_ASSETS_DIR", str(base_dir / "shared_assets"))
        )
        proof_output_dir = Path(
            os.getenv("PROOF_OUTPUT_DIR", str(shared_assets_dir / "proofs"))
        )

        vault_bank_key = os.getenv("VELLUM_BANK_KEY", "vellum-bank")
        default_mapping = {os.getenv("BANK_KEY_ID", "bank-key-1"): vault_bank_key}
        mapping_raw = os.getenv("BANK_KEY_MAPPING_JSON", json.dumps(default_mapping))
        try:
            bank_key_mapping = json.loads(mapping_raw)
        except json.JSONDecodeError as exc:  # pragma: no cover
            raise ValueError("BANK_KEY_MAPPING_JSON must be valid JSON") from exc
        if not isinstance(bank_key_mapping, dict):
            raise ValueError("BANK_KEY_MAPPING_JSON must decode to object")

        security_profile = os.getenv("SECURITY_PROFILE", "strict").strip().lower()
        tls_ca_bundle = os.getenv("TLS_CA_BUNDLE")
        settings = cls(
            app_name=os.getenv("APP_NAME", "vellum-core"),
            circuits_dir=circuits_dir,
            shared_assets_dir=shared_assets_dir,
            proof_output_dir=proof_output_dir,
            snarkjs_bin=os.getenv("SNARKJS_BIN", "snarkjs"),
            database_url=os.getenv(
                "DATABASE_URL", "postgresql+asyncpg://vellum:vellum@postgres:5432/vellum"
            ),
            celery_broker_url=os.getenv("CELERY_BROKER_URL", "redis://redis:6379/0"),
            celery_queue=os.getenv("CELERY_QUEUE", "vellum-queue"),
            redis_url=os.getenv("REDIS_URL", "redis://redis:6379/1"),
            vault_addr=os.getenv("VAULT_ADDR", "http://vault:8200"),
            vault_token=os.getenv("VAULT_TOKEN", "root"),
            vault_jwt_key=os.getenv("VELLUM_JWT_KEY", "vellum-jwt"),
            vault_audit_key=os.getenv("VELLUM_AUDIT_KEY", "vellum-audit"),
            vault_bank_key=vault_bank_key,
            bank_key_id=os.getenv("BANK_KEY_ID", "bank-key-1"),
            bank_key_mapping={str(k): str(v) for k, v in bank_key_mapping.items()},
            vault_public_key_cache_ttl_seconds=int(
                os.getenv("VAULT_PUBLIC_KEY_CACHE_TTL_SECONDS", "300")
            ),
            jwt_issuer=os.getenv("JWT_ISSUER", "bank.local"),
            jwt_audience=os.getenv("JWT_AUDIENCE", "sentinel-zk"),
            nonce_window_seconds=int(os.getenv("NONCE_WINDOW_SECONDS", "300")),
            jwt_max_ttl_seconds=max(1, int(os.getenv("JWT_MAX_TTL_SECONDS", "900"))),
            jwt_leeway_seconds=max(0, int(os.getenv("JWT_LEEWAY_SECONDS", "30"))),
            max_parallel_proofs=max(1, int(os.getenv("PROVER_MAX_PARALLEL_PROOFS", "2"))),
            submit_rate_limit_per_minute=max(
                0, int(os.getenv("SUBMIT_RATE_LIMIT_PER_MINUTE", "30"))
            ),
            security_profile=security_profile,
            metrics_require_auth=_parse_bool_env("METRICS_REQUIRE_AUTH", default=True),
            vellum_data_key=os.getenv("VELLUM_DATA_KEY", ""),
            tls_ca_bundle=tls_ca_bundle if tls_ca_bundle else None,
            worker_metrics_host=os.getenv("WORKER_METRICS_HOST", "127.0.0.1"),
            worker_metrics_port=int(os.getenv("WORKER_METRICS_PORT", "9108")),
            native_verify_baseline_seconds=float(
                os.getenv("NATIVE_VERIFY_BASELINE_SECONDS", "0.000005")
            ),
        )
        settings._validate()
        return settings

    def _validate(self) -> None:
        if self.security_profile not in {"strict", "dev"}:
            raise ValueError("SECURITY_PROFILE must be either 'strict' or 'dev'")
        if not self.vellum_data_key:
            raise ValueError("VELLUM_DATA_KEY is required")
        if self.security_profile != "strict":
            return
        if self.vault_token.strip() in {"", "root"}:
            raise ValueError("SECURITY_PROFILE=strict rejects empty or default VAULT_TOKEN")
        if self.vault_addr.startswith("http://"):
            raise ValueError("SECURITY_PROFILE=strict requires VAULT_ADDR to use https://")
        if self.metrics_require_auth is False:
            raise ValueError("SECURITY_PROFILE=strict requires METRICS_REQUIRE_AUTH=true")
        if self.submit_rate_limit_per_minute < 1:
            raise ValueError(
                "SECURITY_PROFILE=strict requires SUBMIT_RATE_LIMIT_PER_MINUTE >= 1"
            )


def _parse_bool_env(name: str, *, default: bool) -> bool:
    raw = os.getenv(name)
    if raw is None:
        return default
    value = raw.strip().lower()
    if value in {"1", "true", "yes", "on"}:
        return True
    if value in {"0", "false", "no", "off"}:
        return False
    raise ValueError(f"{name} must be a boolean value")
