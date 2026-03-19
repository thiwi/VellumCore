from __future__ import annotations

import asyncio
import json
import tempfile
from pathlib import Path
from typing import Any

from sentinel_zk.errors import APIError
from sentinel_zk.providers.base import ProofResult, ZKProvider
from sentinel_zk.registry import CircuitRegistry


class SnarkJSProvider(ZKProvider):
    def __init__(self, *, registry: CircuitRegistry, snarkjs_bin: str = "snarkjs") -> None:
        self.registry = registry
        self.snarkjs_bin = snarkjs_bin

    async def ensure_artifacts(self, circuit_id: str) -> None:
        artifacts = self.registry.get_artifact_paths(circuit_id)
        missing = [
            str(path)
            for path in (
                artifacts.wasm_path,
                artifacts.zkey_path,
                artifacts.verification_key_path,
            )
            if not path.exists()
        ]
        if missing:
            raise APIError(
                status_code=500,
                code="missing_artifacts",
                message="Required circuit artifacts are missing",
                details={"circuit_id": circuit_id, "missing": missing},
            )

    async def generate_proof(
        self, circuit_id: str, private_input: dict[str, Any]
    ) -> ProofResult:
        await self.ensure_artifacts(circuit_id)
        artifacts = self.registry.get_artifact_paths(circuit_id)

        with tempfile.TemporaryDirectory(prefix=f"zkproof-{circuit_id}-") as tmp:
            tmp_path = Path(tmp)
            input_path = tmp_path / "input.json"
            proof_path = tmp_path / "proof.json"
            public_path = tmp_path / "public.json"
            normalized_input = self._normalize_json_value(private_input)
            input_path.write_text(
                json.dumps(normalized_input, separators=(",", ":")),
                encoding="utf-8",
            )

            await self._run(
                [
                    self.snarkjs_bin,
                    "groth16",
                    "fullprove",
                    str(input_path),
                    str(artifacts.wasm_path),
                    str(artifacts.zkey_path),
                    str(proof_path),
                    str(public_path),
                ]
            )

            proof = json.loads(proof_path.read_text(encoding="utf-8"))
            public_signals = json.loads(public_path.read_text(encoding="utf-8"))
            return ProofResult(proof=proof, public_signals=public_signals)

    async def verify_proof(
        self, circuit_id: str, proof: dict[str, Any], public_signals: list[Any]
    ) -> bool:
        await self.ensure_artifacts(circuit_id)
        artifacts = self.registry.get_artifact_paths(circuit_id)

        with tempfile.TemporaryDirectory(prefix=f"zkverify-{circuit_id}-") as tmp:
            tmp_path = Path(tmp)
            proof_path = tmp_path / "proof.json"
            public_path = tmp_path / "public.json"
            proof_path.write_text(json.dumps(proof), encoding="utf-8")
            public_path.write_text(json.dumps(public_signals), encoding="utf-8")

            args = [
                self.snarkjs_bin,
                "groth16",
                "verify",
                str(artifacts.verification_key_path),
                str(public_path),
                str(proof_path),
            ]
            returncode, stdout, stderr = await self._run_process(args)
            if returncode != 0:
                combined = f"{stdout}\n{stderr}"
                if "Invalid proof" in combined:
                    return False
                raise APIError(
                    status_code=500,
                    code="provider_command_failed",
                    message="snarkjs command failed",
                    details={"command": args, "stdout": stdout, "stderr": stderr},
                )
            return "OK!" in stdout

    async def _run(self, args: list[str]) -> str:
        returncode, stdout, stderr = await self._run_process(args)
        if returncode != 0:
            raise APIError(
                status_code=500,
                code="provider_command_failed",
                message="snarkjs command failed",
                details={"command": args, "stdout": stdout, "stderr": stderr},
            )
        return stdout

    async def _run_process(self, args: list[str]) -> tuple[int, str, str]:
        process = await asyncio.create_subprocess_exec(
            *args,
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE,
        )
        stdout_raw, stderr_raw = await process.communicate()
        stdout = stdout_raw.decode("utf-8", errors="replace").strip()
        stderr = stderr_raw.decode("utf-8", errors="replace").strip()
        return process.returncode, stdout, stderr

    def _normalize_json_value(self, value: Any) -> Any:
        if isinstance(value, bool):
            return value
        if isinstance(value, int):
            return str(value)
        if isinstance(value, str):
            return value
        if isinstance(value, list):
            return [self._normalize_json_value(item) for item in value]
        if isinstance(value, dict):
            return {str(k): self._normalize_json_value(v) for k, v in value.items()}
        if value is None:
            return value
        raise APIError(
            status_code=422,
            code="invalid_private_input",
            message="Private input contains non-serializable value",
            details={"value_type": value.__class__.__name__},
        )
