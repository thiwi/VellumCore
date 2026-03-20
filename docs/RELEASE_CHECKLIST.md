# Release Checklist

## Build and packaging

- [ ] `python -m build`
- [ ] `pip install -e .`
- [ ] `vellum circuits list --json`

## Test pyramid

- [ ] Unit tests: `pytest -m unit`
- [ ] Integration tests: `pytest -m integration`
- [ ] Critical E2E (PR gate): `RUN_E2E=1 pytest -m "e2e and critical"`
- [ ] Nightly E2E: `RUN_E2E=1 pytest -m "e2e and nightly"`

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
- [ ] Update `docs/COMPATIBILITY.md`
- [ ] Update `CHANGELOG.md`

## Compatibility report

- [ ] List added APIs in `vellum_core.api`
- [ ] List added/changed SPI interfaces in `vellum_core.spi`
- [ ] Confirm no removed symbols since previous release (or provide migration)
