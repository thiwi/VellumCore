from __future__ import annotations

import asyncio
import json
from dataclasses import dataclass
from pathlib import Path
from typing import Any

import pytest

from vellum_core.errors import APIError
from vellum_core.providers.snarkjs_provider import SnarkJSProvider


@dataclass(frozen=True)
class _ArtifactPaths:
    wasm_path: Path
    zkey_path: Path
    verification_key_path: Path


class _Registry:
    def __init__(self, paths: _ArtifactPaths) -> None:
        self.paths = paths

    def get_artifact_paths(self, circuit_id: str) -> _ArtifactPaths:
        assert circuit_id == "batch_credit_check"
        return self.paths


def _provider(tmp_path: Path, *, create_all: bool = True) -> SnarkJSProvider:
    artifact_dir = tmp_path / "shared_assets" / "batch_credit_check"
    artifact_dir.mkdir(parents=True, exist_ok=True)
    paths = _ArtifactPaths(
        wasm_path=artifact_dir / "batch_credit_check.wasm",
        zkey_path=artifact_dir / "final.zkey",
        verification_key_path=artifact_dir / "verification_key.json",
    )
    if create_all:
        for path in (paths.wasm_path, paths.zkey_path, paths.verification_key_path):
            path.write_text("x", encoding="utf-8")
    else:
        paths.wasm_path.write_text("x", encoding="utf-8")
    return SnarkJSProvider(registry=_Registry(paths), snarkjs_bin="snarkjs")


def test_ensure_artifacts_raises_with_missing_files(tmp_path: Path) -> None:
    provider = _provider(tmp_path, create_all=False)
    with pytest.raises(APIError) as exc:
        asyncio.run(provider.ensure_artifacts("batch_credit_check"))
    assert exc.value.code == "missing_artifacts"
    missing = exc.value.details["missing"]
    assert any(name.endswith("final.zkey") for name in missing)
    assert any(name.endswith("verification_key.json") for name in missing)


def test_generate_proof_success_and_normalizes_ints(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    provider = _provider(tmp_path, create_all=True)

    async def _fake_run(args: list[str]) -> str:
        input_payload = json.loads(Path(args[3]).read_text(encoding="utf-8"))
        assert input_payload["amount"] == "5"
        assert input_payload["items"][1] == "2"
        assert input_payload["items"][0] is True
        assert input_payload["nested"]["n"] == "9"

        Path(args[6]).write_text(json.dumps({"pi_a": ["1"]}), encoding="utf-8")
        Path(args[7]).write_text(json.dumps(["10"]), encoding="utf-8")
        return "ok"

    monkeypatch.setattr(provider, "_run", _fake_run)
    result = asyncio.run(
        provider.generate_proof(
            "batch_credit_check",
            {"amount": 5, "items": [True, 2], "nested": {"n": 9}},
        )
    )
    assert result.proof == {"pi_a": ["1"]}
    assert result.public_signals == ["10"]


def test_verify_proof_ok_result(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    provider = _provider(tmp_path, create_all=True)
    monkeypatch.setattr(provider, "_run_process", lambda _args: asyncio.sleep(0, result=(0, "OK!", "")))
    valid = asyncio.run(provider.verify_proof("batch_credit_check", {"a": 1}, ["2"]))
    assert valid is True


def test_verify_proof_invalid_returns_false(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    provider = _provider(tmp_path, create_all=True)
    monkeypatch.setattr(
        provider,
        "_run_process",
        lambda _args: asyncio.sleep(0, result=(1, "", "Invalid proof")),
    )
    valid = asyncio.run(provider.verify_proof("batch_credit_check", {"a": 1}, ["2"]))
    assert valid is False


def test_verify_proof_other_failure_raises(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    provider = _provider(tmp_path, create_all=True)
    monkeypatch.setattr(
        provider,
        "_run_process",
        lambda _args: asyncio.sleep(0, result=(1, "boom", "fatal")),
    )
    with pytest.raises(APIError) as exc:
        asyncio.run(provider.verify_proof("batch_credit_check", {"a": 1}, ["2"]))
    assert exc.value.code == "provider_command_failed"


def test_run_raises_api_error_on_nonzero_exit(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    provider = _provider(tmp_path, create_all=True)
    monkeypatch.setattr(
        provider,
        "_run_process",
        lambda _args: asyncio.sleep(0, result=(2, "out", "err")),
    )
    with pytest.raises(APIError) as exc:
        asyncio.run(provider._run(["snarkjs", "bad"]))
    assert exc.value.code == "provider_command_failed"


def test_run_process_executes_subprocess(tmp_path: Path) -> None:
    provider = _provider(tmp_path, create_all=True)
    code, out, err = asyncio.run(
        provider._run_process(["python", "-c", "import sys; sys.stdout.write('hello'); sys.stderr.write('warn')"])
    )
    assert code == 0
    assert out == "hello"
    assert err == "warn"


def test_normalize_json_value_unsupported_type_raises(tmp_path: Path) -> None:
    provider = _provider(tmp_path, create_all=True)
    with pytest.raises(APIError) as exc:
        provider._normalize_json_value({"obj": object()})  # type: ignore[arg-type]
    assert exc.value.code == "invalid_private_input"


def test_normalize_json_value_handles_none_and_strings(tmp_path: Path) -> None:
    provider = _provider(tmp_path, create_all=True)
    payload: dict[str, Any] = {"v": None, "s": "abc"}
    normalized = provider._normalize_json_value(payload)
    assert normalized == {"v": None, "s": "abc"}
