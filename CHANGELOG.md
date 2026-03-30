# Changelog

## Unreleased

### Added

- Dead-letter persistence (`dead_letter_jobs`) with deterministic failure triage.
- Admin DLQ endpoints:
  - `GET /v6/ops/dlq`
  - `POST /v6/ops/dlq/{dlq_id}/requeue`
- Periodic lifecycle maintenance worker (`maintenance_worker.py`) for:
  - terminal runtime payload pruning
  - proof/evidence archival to `PROOF_OUTPUT_DIR/archive`

### Changed

- Runtime proof provider is grpc-only (`PROOF_PROVIDER_MODE=grpc`).
- Runtime shadow-mode provider paths are disabled.
- Verifier attestation export now supports audit-log fallback when job proof payloads were pruned.
- Compose verifier runtime now uses explicit `GRPC_PROVER_ENDPOINT` wiring to `native-prover`.
- Native prover verification is native-first with `snarkjs` fallback for compatibility with generated proof tuples.

## 6.0.0 - Resource-Oriented V6 Surface

### Added

- New v6 run resource endpoints:
  - `POST /v6/runs`
  - `GET /v6/runs/{run_id}`
  - `GET /v6/runs/{run_id}/attestation`
- New typed v6 contracts:
  - `RunCreateRequestV6` (discriminated evidence union: `inline|ref`)
  - `RunStatusResponseV6` (`lifecycle_state`, typed `error`)
  - `AttestationResponseV6` (`policy { id, version }`)
- New migration index: `docs/MIGRATIONS.md`.
- New migration guide: `docs/MIGRATION_V5_TO_V6.md`.
- New release notes: `docs/releases/v6.0.0.md`.

### Changed

- Removed v1 and v5 HTTP route surfaces from reference services.
- Migrated supporting service routes to v6 namespace:
  - Prover proof routes now under `/v6/proofs/*`
  - Verifier verification/ops routes now under `/v6/*`
- Dashboard proxies switched to v6 upstream routes.
- Centralized package/API version constants and shared auth dependency factory for HTTP services.
- Package metadata version updated to `6.0.0`.

### Docs

- Updated README, API reference, architecture, operations, compatibility, security, SDK, and release checklist to v6.
- CI release-readiness gate now validates migration and release artifacts without hardcoding a single migration filename.

## 5.0.0-rc1 - Enterprise Contract and Security Gates

### Added

- Dedicated CI contract gate: `pytest -m contract`.
- Dedicated CI security regression gate: `pytest -m security`.
- Snapshot-backed v5 contract tests for:
  - `/v5/policy-runs`
  - `/v5/policy-runs/{run_id}`
  - `/v5/attestations/{attestation_id}`
- RC1 release artifact documentation: `docs/releases/v5.0.0-rc1.md`.

### Changed

- Docker Compose startup now uses a one-shot `framework-init` service that runs
  `setup_framework.sh` before API services become healthy.
- `prover`, `worker`, and `verifier` now depend on successful framework setup,
  reducing E2E startup race conditions.
- Security-critical suites are explicitly marked with `security`.

## 5.0.0 - Policy-Centric Compliance Surface

### Added

- v5 policy workflow endpoints:
  - `POST /v5/policy-runs`
  - `GET /v5/policy-runs/{run_id}`
  - `GET /v5/attestations/{attestation_id}`
- New framework API contracts:
  - `PolicyRunRequest`
  - `PolicyRunResult`
  - `AttestationBundle`
- New SPI extension protocols:
  - `EvidenceStore`
  - `AttestationSigner`
- Policy pack discovery and built-in `lending_risk_v1` manifest.
- Root OSS governance files:
  - `LICENSE` (Apache-2.0)
  - `CONTRIBUTING.md`
  - `CODE_OF_CONDUCT.md`
  - `SECURITY.md`
- CI pipelines for lint/type checks, unit/integration/critical-E2E tests, packaging, and dependency audit.

### Changed

- Framework runtime wiring now includes policy registry, evidence store, policy engine, and attestation service.
- Worker enriches policy runs with deterministic `pass|fail` decisions in metadata.
- v1 endpoints now include deprecation/sunset metadata headers.
- Package metadata updated to v5 and dev dependencies split into optional extras.

### Docs

- Added migration guide: `docs/MIGRATION_V4_TO_V5.md`.
- Added policy-pack documentation: `docs/POLICY_PACKS.md`.
- Updated README and API reference to v5-first positioning.

## 4.0.0 - Framework Buildout

### Added

- Framework-first modules:
  - `vellum_core.api`
  - `vellum_core.spi`
  - `vellum_core.runtime`
- Stable SDK types for proof generation and verification.
- SPI interfaces for provider, artifact store, signer, and job backend.
- Framework CLI entrypoint: `vellum`.
- Extended dashboard into framework console views for health, circuits, audit, trust-speed, and diagnostics.
- New unit, integration, and E2E test suites with PR/nightly split markers.

### Changed

- Verifier/worker/prover wiring now consumes framework runtime abstractions.
- Error handling now accepts framework-level errors in FastAPI handlers.

### Docs

- Added SDK, reference services, compatibility policy, and release checklist documentation.
