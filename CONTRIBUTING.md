# Contributing to Vellum Core

## Development setup

1. Use Python 3.10+.
2. Install runtime + dev dependencies:
   - `pip install -e .[dev]`
3. Run fast checks before opening a PR:
   - `python -m pytest -m unit`
   - `python -m pytest -m integration`
   - `ruff check .`
   - `mypy --follow-imports=skip --ignore-missing-imports vellum_core/api/attestation_service.py vellum_core/api/policy_engine.py vellum_core/policy_registry.py vellum_core/policy_runtime.py`

## PR expectations

- Keep `vellum_core.api` and `vellum_core.spi` changes explicit and documented.
- Include tests for any API, security, or policy-run behavior change.
- Update docs for new endpoints, settings, and migration impact.
- Keep commits focused and reversible.

## Commit and release notes

- Add changelog entries for user-facing changes.
- Breaking changes must include migration notes in `docs/MIGRATION_V4_TO_V5.md`.

## Security and disclosure

- Do not open public issues for vulnerabilities.
- Follow root `SECURITY.md` for responsible disclosure.
