"""CLI entrypoint for the YAML policy transpiler."""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

from vellum_core.policy_compiler.compiler import (
    build_compiler_metadata,
    check_drift,
    generate_policy_artifacts,
    load_policy_spec,
    sync_manifest_compiler_metadata,
    write_generated_artifacts,
)


def build_parser() -> argparse.ArgumentParser:
    """Build command-line parser for vellum-compiler."""
    parser = argparse.ArgumentParser(prog="vellum-compiler")
    sub = parser.add_subparsers(dest="command", required=True)

    validate = sub.add_parser("validate", help="Validate one policy_spec.yaml")
    validate.add_argument("spec_path", type=Path)

    generate = sub.add_parser("generate", help="Generate Python and Circom artifacts")
    generate.add_argument("spec_path", type=Path)
    generate.add_argument("--repo-root", type=Path, default=Path.cwd())
    generate.add_argument(
        "--print-metadata-json",
        action="store_true",
        help="Print compiler metadata as JSON to stdout",
    )

    drift = sub.add_parser(
        "check-drift",
        help="Return non-zero if committed generated artifacts differ from compiler output",
    )
    drift.add_argument("spec_path", type=Path)
    drift.add_argument("--repo-root", type=Path, default=Path.cwd())
    return parser


def main(argv: list[str] | None = None) -> int:
    """Run vellum-compiler CLI."""
    args = build_parser().parse_args(argv)
    spec = load_policy_spec(args.spec_path)

    if args.command == "validate":
        print(f"valid:{args.spec_path}")
        return 0

    artifacts = generate_policy_artifacts(spec)
    repo_root = getattr(args, "repo_root", Path.cwd())
    manifest_path = args.spec_path.parent / "manifest.json"
    metadata = build_compiler_metadata(spec=spec, artifacts=artifacts)

    if args.command == "generate":
        python_path, circom_path, debug_trace_path = write_generated_artifacts(
            repo_root=repo_root,
            spec=spec,
            artifacts=artifacts,
        )
        manifest_updated = sync_manifest_compiler_metadata(
            manifest_path=manifest_path,
            metadata=metadata,
        )
        if args.print_metadata_json:
            print(
                json.dumps(
                    {
                        "policy_id": spec.policy_id,
                        **metadata.as_dict(),
                        "generated_python_path": str(python_path.relative_to(repo_root)),
                        "generated_circom_path": str(circom_path.relative_to(repo_root)),
                        "generated_debug_trace_path": str(debug_trace_path.relative_to(repo_root)),
                        "manifest_updated": manifest_updated,
                    },
                    sort_keys=True,
                )
            )
        else:
            print(f"generated:{python_path}")
            print(f"generated:{circom_path}")
            print(f"generated:{debug_trace_path}")
            if manifest_updated:
                print(f"manifest_updated:{manifest_path}")
        return 0

    assert args.command == "check-drift"
    if not check_drift(
        repo_root=repo_root,
        spec=spec,
        artifacts=artifacts,
        manifest_path=manifest_path,
    ):
        print("drift:detected")
        return 1
    print("drift:none")
    return 0


if __name__ == "__main__":
    sys.exit(main())
