"""Tests for gRPC prover provider."""

from __future__ import annotations

import asyncio
import json
from dataclasses import dataclass
from pathlib import Path

import grpc
import pytest

from vellum_core.errors import APIError
from vellum_core.providers import grpc_prover_provider as grpc_provider_module
from vellum_core.proto import vellum_prover_pb2
from vellum_core.providers.grpc_prover_provider import GrpcProofProvider


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


def _provider(tmp_path: Path, *, create_all: bool = True) -> GrpcProofProvider:
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
    return GrpcProofProvider(
        registry=_Registry(paths),
        endpoint="127.0.0.1:50051",
        timeout_seconds=5.0,
    )


class _FakeRpcError(grpc.RpcError):
    pass


def test_ensure_artifacts_raises_with_missing_files(tmp_path: Path) -> None:
    provider = _provider(tmp_path, create_all=False)
    with pytest.raises(APIError) as exc:
        asyncio.run(provider.ensure_artifacts("batch_credit_check"))
    assert exc.value.code == "missing_artifacts"


def test_generate_proof_success_and_normalizes_ints(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    provider = _provider(tmp_path, create_all=True)

    async def _fake_generate(
        request: vellum_prover_pb2.GenerateProofRequest,
    ) -> vellum_prover_pb2.GenerateProofResponse:
        private_input = json.loads(request.private_input_json)
        assert private_input["amount"] == "5"
        assert private_input["items"][0] is True
        assert private_input["items"][1] == "2"
        assert private_input["nested"]["count"] == "9"
        return vellum_prover_pb2.GenerateProofResponse(
            proof_json='{"pi_a":["1"]}',
            public_signals_json='["10","1"]',
        )

    monkeypatch.setattr(provider, "_call_generate", _fake_generate)
    result = asyncio.run(
        provider.generate_proof(
            "batch_credit_check",
            {"amount": 5, "items": [True, 2], "nested": {"count": 9}},
        )
    )
    assert result.proof == {"pi_a": ["1"]}
    assert result.public_signals == ["10", "1"]


def test_generate_proof_rpc_failure_raises(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    provider = _provider(tmp_path, create_all=True)

    async def _boom(
        _request: vellum_prover_pb2.GenerateProofRequest,
    ) -> vellum_prover_pb2.GenerateProofResponse:
        raise _FakeRpcError("unavailable")

    monkeypatch.setattr(provider, "_call_generate", _boom)
    with pytest.raises(APIError) as exc:
        asyncio.run(provider.generate_proof("batch_credit_check", {"v": 1}))
    assert exc.value.code == "provider_command_failed"


def test_verify_proof_success(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    provider = _provider(tmp_path, create_all=True)

    async def _fake_verify(
        request: vellum_prover_pb2.VerifyProofRequest,
    ) -> vellum_prover_pb2.VerifyProofResponse:
        assert request.circuit_id == "batch_credit_check"
        assert json.loads(request.proof_json) == {"a": "b"}
        assert json.loads(request.public_signals_json) == ["1", "2"]
        return vellum_prover_pb2.VerifyProofResponse(valid=True)

    monkeypatch.setattr(provider, "_call_verify", _fake_verify)
    valid = asyncio.run(provider.verify_proof("batch_credit_check", {"a": "b"}, ["1", "2"]))
    assert valid is True


def test_verify_proof_rpc_failure_raises(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    provider = _provider(tmp_path, create_all=True)

    async def _boom(
        _request: vellum_prover_pb2.VerifyProofRequest,
    ) -> vellum_prover_pb2.VerifyProofResponse:
        raise _FakeRpcError("deadline")

    monkeypatch.setattr(provider, "_call_verify", _boom)
    with pytest.raises(APIError) as exc:
        asyncio.run(provider.verify_proof("batch_credit_check", {"x": 1}, ["1"]))
    assert exc.value.code == "provider_command_failed"


def test_normalize_json_value_unsupported_type_raises(tmp_path: Path) -> None:
    provider = _provider(tmp_path, create_all=True)
    with pytest.raises(APIError) as exc:
        provider._normalize_json_value({"obj": object()})  # type: ignore[arg-type]
    assert exc.value.code == "invalid_private_input"


def test_get_stub_reuses_single_channel(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    provider = _provider(tmp_path, create_all=True)
    channel_calls: list[str] = []

    class _FakeStub:
        def __init__(self, _channel: object) -> None:
            self.channel = _channel

    def _fake_insecure_channel(endpoint: str) -> object:
        channel_calls.append(endpoint)
        return object()

    monkeypatch.setattr(
        grpc_provider_module.grpc.aio,
        "insecure_channel",
        _fake_insecure_channel,
    )
    monkeypatch.setattr(
        grpc_provider_module.vellum_prover_pb2_grpc,
        "ProverStub",
        _FakeStub,
    )

    async def _run_same_loop() -> tuple[object, object]:
        first = await provider._get_stub()
        second = await provider._get_stub()
        return first, second

    stub_first, stub_second = asyncio.run(_run_same_loop())

    assert stub_first is stub_second
    assert channel_calls == ["127.0.0.1:50051"]


def test_get_stub_recreates_channel_when_event_loop_changes(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    provider = _provider(tmp_path, create_all=True)
    channel_calls: list[str] = []
    closed_channels: list[str] = []
    channel_index = {"value": 0}

    class _FakeChannel:
        def __init__(self, name: str) -> None:
            self.name = name

        async def close(self) -> None:
            closed_channels.append(self.name)

    class _FakeStub:
        def __init__(self, channel: _FakeChannel) -> None:
            self.channel = channel

    def _fake_insecure_channel(endpoint: str) -> _FakeChannel:
        channel_calls.append(endpoint)
        channel_index["value"] += 1
        return _FakeChannel(f"ch-{channel_index['value']}")

    monkeypatch.setattr(
        grpc_provider_module.grpc.aio,
        "insecure_channel",
        _fake_insecure_channel,
    )
    monkeypatch.setattr(
        grpc_provider_module.vellum_prover_pb2_grpc,
        "ProverStub",
        _FakeStub,
    )

    stub_first = asyncio.run(provider._get_stub())
    stub_second = asyncio.run(provider._get_stub())

    assert stub_first is not stub_second
    assert channel_calls == ["127.0.0.1:50051", "127.0.0.1:50051"]
    assert closed_channels == ["ch-1"]
