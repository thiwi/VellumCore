# Changelog

## 4.0.0 - Framework Buildout

### Added

- Framework-first modules:
  - `vellum_core.api`
  - `vellum_core.spi`
  - `vellum_core.runtime`
- Stable SDK types for proof generation and verification.
- SPI interfaces for provider, artifact store, adapter, signer, and job backend.
- Framework CLI entrypoint: `vellum`.
- Extended dashboard into framework console views for health, circuits, audit, trust-speed, and diagnostics.
- New unit, integration, and E2E test suites with PR/nightly split markers.

### Changed

- Verifier/worker/prover wiring now consumes framework runtime abstractions.
- Error handling now accepts framework-level errors in FastAPI handlers.

### Docs

- Added SDK, reference services, compatibility policy, and release checklist documentation.
