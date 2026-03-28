# Development Guide

## Prerequisites

- Python 3.10+
- Docker + Docker Compose
- `snarkjs` and `circom` only needed if building artifacts outside container workflows

## Install

```bash
pip install -e .[dev]
```

## Framework CLI

```bash
vellum circuits list
vellum circuits validate --json
vellum-compiler validate policy_packs/lending_risk_v1/policy_spec.yaml
vellum-compiler check-drift policy_packs/lending_risk_v1/policy_spec.yaml --repo-root .
```

## Test Strategy

Run fast layers first:

```bash
python -m pytest -m unit
python -m pytest -m integration
python -m pytest -m contract
python -m pytest -m security
```

Run compose E2E when changing service wiring or auth flows:

```bash
RUN_E2E=1 python -m pytest -m "e2e and critical"
RUN_E2E=1 python -m pytest -m e2e -q
```

Contract snapshots:

- Contract tests compare v5 HTTP/model schemas against files in `tests/contracts/snapshots/`.
- If an intentional API contract change is made, update those snapshots in the same PR.

Static checks:

```bash
ruff check .
mypy --follow-imports=skip --ignore-missing-imports vellum_core/api/attestation_service.py vellum_core/api/policy_engine.py vellum_core/policy_registry.py vellum_core/policy_runtime.py
```

Native prover (optional local run):

```bash
cd native_prover
cargo run --release -- --addr 0.0.0.0:50051 --snarkjs-bin snarkjs
```

Provider benchmark + cutover gate (manual/local):

```bash
RUNS=40 DAYS_OBSERVED=0 COMPARED_RUNS=0 FUNCTIONAL_MISMATCHES=0 \
  ./systematic_study/run_provider_benchmark.sh
```

## Coding Standards

- Keep framework contracts in `vellum_core.api` and `vellum_core.spi` stable.
- Put reference-service-specific request/response models in `vellum_core.schemas`.
- Preserve explicit error codes/messages through `APIError` for operator usability.
- Avoid hidden side effects in workers; persist state transitions explicitly.

## Adding a New Circuit (Reference Deployment)

1. Add circuit folder and `manifest.json` in `circuits/`.
2. Generate artifacts into `shared_assets/<circuit_id>/`.
3. Validate discovery:
   - `vellum circuits list`
   - `vellum circuits validate --json`
4. Submit proof with `circuit_id` + `private_input`.

## Extending the Framework

Prefer extension via SPI protocols:

- `ProofProvider`
- `ArtifactStore`
- `Signer`
- `JobBackend`

Wire implementations via runtime composition (`vellum_core/runtime/defaults.py`).
