# Changelog

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
