from __future__ import annotations

import os
from dataclasses import dataclass
from pathlib import Path


@dataclass(frozen=True)
class Settings:
    app_name: str
    circuits_dir: Path
    shared_assets_dir: Path
    shared_store_file: Path
    proof_output_dir: Path
    snarkjs_bin: str
    jwt_issuer: str
    jwt_audience: str
    jwt_public_key_path: Path
    bank_public_keys_path: Path
    audit_private_key_path: Path
    audit_public_key_path: Path
    nonce_window_seconds: int
    max_parallel_proofs: int

    @classmethod
    def from_env(cls) -> "Settings":
        base_dir = Path(os.getenv("APP_BASE_DIR", Path.cwd()))
        circuits_dir = Path(os.getenv("CIRCUITS_DIR", str(base_dir / "circuits")))
        shared_assets_dir = Path(
            os.getenv("SHARED_ASSETS_DIR", str(base_dir / "shared_assets"))
        )
        shared_store_file = Path(
            os.getenv(
                "PROOF_STORE_FILE", str(base_dir / "shared_store" / "proof_audit.jsonl")
            )
        )
        proof_output_dir = Path(
            os.getenv("PROOF_OUTPUT_DIR", str(shared_assets_dir / "proofs"))
        )

        return cls(
            app_name=os.getenv("APP_NAME", "sentinel-zk-core"),
            circuits_dir=circuits_dir,
            shared_assets_dir=shared_assets_dir,
            shared_store_file=shared_store_file,
            proof_output_dir=proof_output_dir,
            snarkjs_bin=os.getenv("SNARKJS_BIN", "snarkjs"),
            jwt_issuer=os.getenv("JWT_ISSUER", "bank.local"),
            jwt_audience=os.getenv("JWT_AUDIENCE", "sentinel-zk"),
            jwt_public_key_path=Path(
                os.getenv("JWT_PUBLIC_KEY_PATH", str(base_dir / "config" / "jwt_public.pem"))
            ),
            bank_public_keys_path=Path(
                os.getenv(
                    "BANK_PUBLIC_KEYS_PATH",
                    str(base_dir / "config" / "bank_public_keys.json"),
                )
            ),
            audit_private_key_path=Path(
                os.getenv(
                    "AUDIT_PRIVATE_KEY_PATH", str(base_dir / "config" / "audit_private.pem")
                )
            ),
            audit_public_key_path=Path(
                os.getenv(
                    "AUDIT_PUBLIC_KEY_PATH", str(base_dir / "config" / "audit_public.pem")
                )
            ),
            nonce_window_seconds=int(os.getenv("NONCE_WINDOW_SECONDS", "300")),
            max_parallel_proofs=max(1, int(os.getenv("PROVER_MAX_PARALLEL_PROOFS", "2"))),
        )
