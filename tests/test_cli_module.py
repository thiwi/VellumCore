from __future__ import annotations

from argparse import Namespace
from dataclasses import dataclass
from typing import Any

import pytest

import vellum_core.cli as cli


@dataclass
class _ValidationRow:
    circuit_id: str
    artifacts_ready: bool
    version: str

    def model_dump(self) -> dict[str, Any]:
        return {
            "circuit_id": self.circuit_id,
            "artifacts_ready": self.artifacts_ready,
            "version": self.version,
        }


class _FakeCircuitManager:
    def list(self) -> list[str]:
        return ["alpha", "beta"]

    def list_with_validation(self) -> list[_ValidationRow]:
        return [
            _ValidationRow(circuit_id="alpha", artifacts_ready=True, version="1"),
            _ValidationRow(circuit_id="beta", artifacts_ready=False, version="2"),
        ]


class _FakeFramework:
    def __init__(self) -> None:
        self.circuit_manager = _FakeCircuitManager()


class _FakeFrameworkClient:
    @classmethod
    def from_env(cls) -> _FakeFramework:
        return _FakeFramework()


def test_print_json_is_pretty_and_sorted(capsys: pytest.CaptureFixture[str]) -> None:
    cli._print_json({"b": 2, "a": 1})
    out = capsys.readouterr().out
    assert out == '{\n  "a": 1,\n  "b": 2\n}\n'


def test_cmd_circuits_list_text(monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]) -> None:
    monkeypatch.setattr(cli, "FrameworkClient", _FakeFrameworkClient)
    code = cli._cmd_circuits_list(as_json=False)
    assert code == 0
    assert capsys.readouterr().out.splitlines() == ["alpha", "beta"]


def test_cmd_circuits_list_json(monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]) -> None:
    monkeypatch.setattr(cli, "FrameworkClient", _FakeFrameworkClient)
    code = cli._cmd_circuits_list(as_json=True)
    assert code == 0
    out = capsys.readouterr().out
    assert '"circuits": [' in out
    assert '"alpha"' in out


def test_cmd_circuits_validate_text(monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]) -> None:
    monkeypatch.setattr(cli, "FrameworkClient", _FakeFrameworkClient)
    code = cli._cmd_circuits_validate(as_json=False)
    assert code == 0
    assert capsys.readouterr().out.splitlines() == [
        "alpha: ready (version=1)",
        "beta: missing (version=2)",
    ]


def test_cmd_circuits_validate_json(monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]) -> None:
    monkeypatch.setattr(cli, "FrameworkClient", _FakeFrameworkClient)
    code = cli._cmd_circuits_validate(as_json=True)
    assert code == 0
    out = capsys.readouterr().out
    assert '"circuits": [' in out
    assert '"circuit_id": "alpha"' in out


def test_main_dispatches_list(monkeypatch: pytest.MonkeyPatch) -> None:
    parser = cli.build_parser()
    monkeypatch.setattr(parser, "parse_args", lambda: Namespace(command="circuits", circuits_command="list", json=True))
    monkeypatch.setattr(cli, "build_parser", lambda: parser)
    monkeypatch.setattr(cli, "_cmd_circuits_list", lambda as_json: 123 if as_json else 0)
    assert cli.main() == 123


def test_main_dispatches_validate(monkeypatch: pytest.MonkeyPatch) -> None:
    parser = cli.build_parser()
    monkeypatch.setattr(
        parser,
        "parse_args",
        lambda: Namespace(command="circuits", circuits_command="validate", json=False),
    )
    monkeypatch.setattr(cli, "build_parser", lambda: parser)
    monkeypatch.setattr(cli, "_cmd_circuits_validate", lambda as_json: 321 if not as_json else 0)
    assert cli.main() == 321


def test_main_unsupported_command_returns_2(monkeypatch: pytest.MonkeyPatch) -> None:
    class _Parser:
        def __init__(self) -> None:
            self.error_called = False

        def parse_args(self) -> Namespace:
            return Namespace(command="oops", circuits_command="x", json=False)

        def error(self, _msg: str) -> None:
            self.error_called = True

    parser = _Parser()
    monkeypatch.setattr(cli, "build_parser", lambda: parser)
    assert cli.main() == 2
    assert parser.error_called is True
