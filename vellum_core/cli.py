"""Command-line interface for circuit discovery and artifact validation."""

from __future__ import annotations

import argparse
import json

from vellum_core.api import FrameworkClient


def _print_json(payload: object) -> None:
    """Print deterministic pretty JSON output for CLI commands."""
    print(json.dumps(payload, indent=2, sort_keys=True))


def _cmd_circuits_list(as_json: bool) -> int:
    """Handle `vellum circuits list` command."""
    framework = FrameworkClient.from_env()
    circuits = framework.circuit_manager.list()
    if as_json:
        _print_json({"circuits": circuits})
    else:
        for circuit_id in circuits:
            print(circuit_id)
    return 0


def _cmd_circuits_validate(as_json: bool) -> int:
    """Handle `vellum circuits validate` command."""
    framework = FrameworkClient.from_env()
    status = [entry.model_dump() for entry in framework.circuit_manager.list_with_validation()]
    if as_json:
        _print_json({"circuits": status})
    else:
        for row in status:
            ready = "ready" if row["artifacts_ready"] else "missing"
            print(f"{row['circuit_id']}: {ready} (version={row['version']})")
    return 0


def build_parser() -> argparse.ArgumentParser:
    """Create root argparse parser and subcommands."""
    parser = argparse.ArgumentParser(description="Vellum Core framework CLI")
    sub = parser.add_subparsers(dest="command", required=True)

    circuits = sub.add_parser("circuits", help="inspect circuits and artifact state")
    circuits_sub = circuits.add_subparsers(dest="circuits_command", required=True)

    circuits_list = circuits_sub.add_parser("list", help="list discovered circuits")
    circuits_list.add_argument("--json", action="store_true")

    circuits_validate = circuits_sub.add_parser("validate", help="validate artifact availability")
    circuits_validate.add_argument("--json", action="store_true")

    return parser


def main() -> int:
    """CLI entrypoint returning shell-compatible exit code."""
    parser = build_parser()
    args = parser.parse_args()

    if args.command == "circuits" and args.circuits_command == "list":
        return _cmd_circuits_list(args.json)

    if args.command == "circuits" and args.circuits_command == "validate":
        return _cmd_circuits_validate(args.json)

    parser.error("unsupported command")
    return 2


if __name__ == "__main__":
    raise SystemExit(main())
