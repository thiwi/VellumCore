# Troubleshooting

## Startup Failures

### `dependency failed to start` in compose

- Check `docker compose ps -a` and service logs.
- Typical cause: race during first DB initialization.
- Retry start for affected service after dependencies are healthy.

### Vault/bootstrap issues

- Confirm `vault` is healthy.
- Ensure `vault-init` completed successfully.
- Verify transit keys exist (`vellum-jwt`, `vellum-audit`, `vellum-bank`).

## Auth Errors

### `missing_token` / `invalid_token`

- Verify bearer token is present and minted with expected issuer/audience.
- Ensure verifier/prover use same JWT key and Vault source.

### `missing_handshake_headers` / `invalid_handshake_signature`

- Check all `X-Bank-*` headers are present.
- Recompute canonical signature string exactly.
- Confirm `X-Bank-Key-Id` maps to the expected Vault key.

### `nonce_replay` / `stale_request`

- Ensure unique nonce per request.
- Ensure timestamps are synchronized and inside nonce window.

## Proving / Verification Issues

### `missing_artifacts` or proof generation failure

- Run artifact setup:

```bash
docker compose exec prover /app/setup_framework.sh
```

- Re-check with `vellum circuits validate --json`.

### Verification invalid unexpectedly

- Confirm matching `circuit_id`, `proof`, `public_signals` tuple.
- Check that proof payload was not modified after generation.

## Data / Audit Issues

### Audit chain invalid

- Run `GET /v1/audit/verify-chain` and inspect first broken index.
- Investigate signing key version changes and entry ordering.
- Avoid manual DB edits to `audit_log`.

## Dashboard Issues

### Empty/partial cockpit data

- Check `/api/framework/overview` response directly.
- Verify upstream prover/verifier reachability from dashboard container.
- Check browser console/network for failed API calls.
