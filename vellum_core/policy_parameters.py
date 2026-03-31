"""Policy parameter loading and hashing helpers."""

from __future__ import annotations

import hashlib
import json
from pathlib import Path
from typing import Any

from vellum_core.api.errors import framework_error


def compute_policy_params_hash(parameters: dict[str, int]) -> str:
    """Return deterministic SHA-256 hash for canonical policy parameters."""
    canonical = json.dumps(parameters, sort_keys=True, separators=(",", ":")).encode("utf-8")
    return hashlib.sha256(canonical).hexdigest()


class PolicyParameterStore:
    """Filesystem-backed parameter store for policy run parameter references."""

    def __init__(self, *, policy_packs_dir: Path) -> None:
        self.policy_packs_dir = policy_packs_dir

    def resolve(self, *, policy_id: str, policy_params_ref: str | None) -> dict[str, int]:
        """Resolve one parameter reference to a validated integer map."""
        if policy_params_ref is None or policy_params_ref.strip() == "":
            return {}

        ref = policy_params_ref.strip()
        if ".." in ref or "/" in ref or "\\" in ref:
            raise framework_error(
                "invalid_policy_params_ref",
                "Policy parameter reference must be a plain file stem",
                policy_id=policy_id,
                policy_params_ref=policy_params_ref,
            )

        path = self.policy_packs_dir / policy_id / "params" / f"{ref}.json"
        if not path.exists():
            raise framework_error(
                "unknown_policy_params_ref",
                "Policy parameter reference not found",
                policy_id=policy_id,
                policy_params_ref=policy_params_ref,
                path=str(path),
            )

        try:
            payload: Any = json.loads(path.read_text(encoding="utf-8"))
        except json.JSONDecodeError as exc:
            raise framework_error(
                "invalid_policy_params_ref",
                "Policy parameter file is not valid JSON",
                policy_id=policy_id,
                policy_params_ref=policy_params_ref,
                path=str(path),
            ) from exc

        if not isinstance(payload, dict):
            raise framework_error(
                "invalid_policy_params_ref",
                "Policy parameter file must decode to an object",
                policy_id=policy_id,
                policy_params_ref=policy_params_ref,
                path=str(path),
            )

        normalized: dict[str, int] = {}
        for key, value in payload.items():
            if isinstance(value, bool):
                raise framework_error(
                    "invalid_policy_params_ref",
                    "Policy parameter values must be integers",
                    policy_id=policy_id,
                    policy_params_ref=policy_params_ref,
                    parameter=str(key),
                    value=value,
                )
            if not isinstance(value, int):
                raise framework_error(
                    "invalid_policy_params_ref",
                    "Policy parameter values must be integers",
                    policy_id=policy_id,
                    policy_params_ref=policy_params_ref,
                    parameter=str(key),
                    value=value,
                )
            normalized[str(key)] = int(value)
        return normalized

