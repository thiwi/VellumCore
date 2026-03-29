# CI and Quality Gates

This document describes the GitHub CI workflow checks for `main` and how to reproduce them locally.

## Workflow Scope

Primary workflow: [`.github/workflows/ci.yml`](../.github/workflows/ci.yml)

Triggers:

- pull requests
- pushes to `main`

Workflow-level controls:

- concurrency cancellation: `ci-${{ github.workflow }}-${{ github.ref }}` with `cancel-in-progress: true`
- GitHub action runtime compatibility pin: `FORCE_JAVASCRIPT_ACTIONS_TO_NODE24=true`
- docs-only PR short-circuit (jobs remain present/green, heavy steps are skipped)

## CI Jobs

- `changes`: path filter used for docs-only short-circuit decisions
- `lint_type`: Ruff + MyPy + requirements drift + policy compiler drift
- `unit_tests`: pytest unit marker
- `integration_tests`: pytest integration marker
- `contract_tests`: pytest contract marker
- `security_regression`: pytest security marker
- `critical_e2e`: critical E2E marker
- `package_build`: Python package build (`python -m build`)
- `native_prover_tests`: Rust native prover tests
- `security_scan`: dependency CVE scan with `pip-audit`
- `release_readiness`: required release docs/artifacts presence check

## Reusable Setup and Caching

Python jobs use one shared composite action:

- [`.github/actions/python-dev-setup/action.yml`](../.github/actions/python-dev-setup/action.yml)

It centralizes:

- checkout
- `actions/setup-python@v5` with pip cache
- dependency install

Additional cache:

- Rust cache via `Swatinem/rust-cache@v2` in `native_prover_tests`

## Dependency Governance

Canonical dependency source:

- [`pyproject.toml`](../pyproject.toml) (`[project].dependencies`)

Export/check tool:

- [`scripts/sync_requirements.py`](../scripts/sync_requirements.py)

Rules:

- `requirements.txt` is committed and still consumed by Dockerfiles + `pip-audit`
- CI fails if `requirements.txt` drifts from `pyproject.toml` (`python scripts/sync_requirements.py check`)

## Local Reproduction (CI Parity)

Install dev dependencies:

```bash
pip install -e .[dev]
```

Run CI-equivalent checks:

```bash
ruff check .
mypy --follow-imports=skip --ignore-missing-imports vellum_core/api/attestation_service.py vellum_core/api/policy_engine.py vellum_core/policy_registry.py vellum_core/policy_runtime.py
python scripts/sync_requirements.py check
python -m pytest -m unit
python -m pytest -m integration
python -m pytest -m contract
python -m pytest -m security
RUN_E2E=1 python -m pytest -m "e2e and critical"
cargo test --manifest-path native_prover/Cargo.toml
pip install pip-audit
pip-audit -r requirements.txt
python -m build
```

Optional local export (after dependency changes):

```bash
python scripts/sync_requirements.py export
```

If `cargo test` fails with missing `protoc`, install Protocol Buffers compiler first:

- Ubuntu/Debian: `sudo apt-get install -y protobuf-compiler`
- macOS: `brew install protobuf`
