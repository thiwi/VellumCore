# CI and Quality Gates

This document describes the GitHub CI workflow checks for `main` and how to reproduce them locally.

## Workflow Scope

The primary workflow is [`.github/workflows/ci.yml`](../.github/workflows/ci.yml) and runs on:

- pull requests
- pushes to `main`

## CI Jobs

- `lint_type`: Ruff + MyPy + policy compiler drift gate
- `unit_tests`: pytest unit marker
- `integration_tests`: pytest integration marker
- `contract_tests`: pytest contract marker
- `security_regression`: pytest security marker
- `critical_e2e`: critical E2E marker
- `package_build`: Python package build (`python -m build`)
- `native_prover_tests`: Rust native prover tests
- `security_scan`: dependency CVE scan with `pip-audit`
- `release_readiness`: required release docs/artifacts presence check

## Security and Native-Prover Gates

Two gates are especially important for release safety:

1. Dependency CVE gate
   - command: `pip-audit -r requirements.txt`
   - fails CI when known vulnerabilities are present in pinned dependencies

2. Native prover build/test gate
   - command: `cargo test --manifest-path native_prover/Cargo.toml`
   - requires `protoc` for protobuf code generation (installed in CI runner)

## Local Reproduction

Install dev dependencies:

```bash
pip install -e .[dev]
```

Run CI-equivalent checks:

```bash
ruff check .
mypy --follow-imports=skip --ignore-missing-imports vellum_core/api/attestation_service.py vellum_core/api/policy_engine.py vellum_core/policy_registry.py vellum_core/policy_runtime.py
python -m pytest -m unit
python -m pytest -m integration
python -m pytest -m contract
python -m pytest -m security
RUN_E2E=1 python -m pytest -m "e2e and critical"
pip install pip-audit
pip-audit -r requirements.txt
cargo test --manifest-path native_prover/Cargo.toml
```

If `cargo test` fails with missing `protoc`, install:

- Ubuntu/Debian: `sudo apt-get install -y protobuf-compiler`
- macOS: `brew install protobuf`

## Notes

- CI currently emits a GitHub-hosted warning about Node.js 20-based actions.
- This is a platform deprecation warning from GitHub Actions and does not currently fail the workflow.
