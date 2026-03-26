# Compatibility and Deprecation Policy

## Versioning

- Vellum Core follows SemVer for framework modules in `vellum_core.api` and `vellum_core.spi`.
- v5 introduces a deliberate API reset toward policy-centric workflows.
- Patch releases: bug fixes, no breaking API changes.
- Minor releases: additive API changes; deprecations may be introduced.
- Major releases: breaking API changes.

## Deprecation window

- Deprecated API symbols are supported for at least one minor release after deprecation.
- Deprecations are documented in `CHANGELOG.md` with migration guidance.

## Compatibility scope

Guaranteed stable contract:
- `vellum_core.api`
- `vellum_core.spi`

Best-effort compatibility:
- reference service endpoints and operational scripts
