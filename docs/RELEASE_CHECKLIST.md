# Release Checklist

## Build and packaging

- [ ] `python -m build`
- [ ] `pip install -e .[dev]`
- [ ] `vellum circuits list --json`
- [ ] `ruff check .`
- [ ] `mypy vellum_core`

## Test pyramid

- [ ] Unit tests: `python -m pytest -m unit`
- [ ] Integration tests: `python -m pytest -m integration`
- [ ] Contract tests: `python -m pytest -m contract`
- [ ] Security regressions: `python -m pytest -m security`
- [ ] Critical E2E (PR gate): `RUN_E2E=1 python -m pytest -m "e2e and critical"`
- [ ] Nightly E2E: `RUN_E2E=1 python -m pytest -m "e2e and nightly"`
- [ ] Contract snapshots reviewed/updated in `tests/contracts/snapshots/` when API schema changes

## Documentation

- [ ] Update `README.md`
- [ ] Update `docs/README.md` (documentation index)
- [ ] Update `docs/ARCHITECTURE.md`
- [ ] Update `docs/API_REFERENCE.md`
- [ ] Update `docs/CONFIGURATION.md`
- [ ] Update `docs/OPERATIONS.md`
- [ ] Update `docs/DEVELOPMENT.md`
- [ ] Update `docs/SECURITY.md`
- [ ] Update `docs/TROUBLESHOOTING.md`
- [ ] Update `docs/SDK.md`
- [ ] Update `docs/MIGRATION_V4_TO_V5.md` when breaking changes occur
- [ ] Update `docs/COMPATIBILITY.md`
- [ ] Update release notes in `docs/releases/` for the release tag
- [ ] Update `CHANGELOG.md`

## Compatibility report

- [ ] List added APIs in `vellum_core.api`
- [ ] List added/changed SPI interfaces in `vellum_core.spi`
- [ ] Confirm no removed symbols since previous release (or provide migration)
