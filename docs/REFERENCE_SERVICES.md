# Reference Services

The reference deployment is an operational blueprint built on top of the SDK.

## Services

- `prover_service.py`: authenticated job intake and queue submission
- `worker.py`: asynchronous proof execution and artifact output persistence
- `verifier_service.py`: proof verification, circuit status, trust-speed, and audit validation
- `dashboard_service.py`: operations cockpit and API aggregation/proxy layer

## Startup Behavior (Compose)

- `framework-init` runs once to prepare circuit artifacts before service health gates.
- `prover`, `worker`, and `verifier` depend on successful `framework-init` completion.
- Rebuild artifacts on demand with: `docker compose run --rm framework-init`

## Primary v5 Endpoints

- Prover:
  - `POST /v5/policy-runs`
  - `GET /v5/policy-runs/{run_id}`
- Verifier:
  - `GET /v5/attestations/{attestation_id}`

## Intended Use

- Demonstrate production-like wiring (auth, queue, storage, audit chain).
- Provide a concrete baseline for infra and monitoring.
- Serve as executable examples for integration patterns.

## Non-Goals

- These endpoints are not the only integration model.
- They are best-effort stable, unlike `vellum_core.api` and `vellum_core.spi`.

Teams that need strict long-term API stability should integrate via the SDK contract.
