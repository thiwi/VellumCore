# Compatibility and Deprecation Policy

## Versioning

- Vellum Core follows SemVer for framework modules in `vellum_core.api` and `vellum_core.spi`.
- v6 introduces a resource-oriented HTTP surface for policy run lifecycle endpoints.
- Patch releases: bug fixes, no breaking API changes.
- Minor releases: additive API changes; deprecations may be introduced.
- Major releases: breaking API changes.

## Deprecation window

- Breaking HTTP transitions require a migration guide in `docs/MIGRATIONS.md`.
- Deprecations and removals are documented in `CHANGELOG.md` with migration guidance.

## Compatibility scope

Guaranteed stable contract:
- `vellum_core.api`
- `vellum_core.spi`

Best-effort compatibility:
- reference service endpoints and operational scripts
