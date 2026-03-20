# Reference Services

The reference deployment is an operational blueprint built on top of the SDK.

## Services

- `prover_service.py`: authenticated job intake and queue submission
- `worker.py`: asynchronous proof execution and artifact output persistence
- `verifier_service.py`: proof verification, circuit status, trust-speed, and audit validation
- `dashboard_service.py`: operations cockpit and API aggregation/proxy layer

## Intended Use

- Demonstrate production-like wiring (auth, queue, storage, audit chain).
- Provide a concrete baseline for infra and monitoring.
- Serve as executable examples for integration patterns.

## Non-Goals

- These endpoints are not the only integration model.
- They are best-effort stable, unlike `vellum_core.api` and `vellum_core.spi`.

Teams that need strict long-term API stability should integrate via the SDK contract.
