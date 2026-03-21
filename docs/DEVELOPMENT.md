# Development Guide

## Prerequisites

- Python 3.10+
- Docker + Docker Compose
- `snarkjs` and `circom` only needed if building artifacts outside container workflows

## Install

```bash
pip install -e .
```

## Framework CLI

```bash
vellum circuits list
vellum circuits validate --json
```

## Test Strategy

Run fast layers first:

```bash
pytest -m unit
pytest -m integration
```

Run compose E2E when changing service wiring or auth flows:

```bash
RUN_E2E=1 pytest -m "e2e and critical"
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
