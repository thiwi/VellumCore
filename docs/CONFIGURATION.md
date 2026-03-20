# Configuration

## Principles

- Keep secrets in environment or secret manager; do not hardcode in source.
- Use explicit environment values per service even when defaults exist.
- Validate startup health (`/healthz`) after any config change.

## Key Environment Variables

Loaded by `Settings.from_env()` in `vellum_core/config.py`.

### App and Paths

- `APP_NAME` (default: `vellum-core`)
- `CIRCUITS_DIR` (default: `<cwd>/circuits`)
- `SHARED_ASSETS_DIR` (default: `<cwd>/shared_assets`)
- `PROOF_OUTPUT_DIR` (default: `<shared_assets>/proofs`)
- `SNARKJS_BIN` (default: `snarkjs`)

### Data Plane

- `DATABASE_URL`
- `CELERY_BROKER_URL`
- `CELERY_QUEUE`
- `REDIS_URL`

### Vault and Keys

- `VAULT_ADDR`
- `VAULT_TOKEN`
- `VELLUM_JWT_KEY`
- `VELLUM_AUDIT_KEY`
- `VELLUM_BANK_KEY`
- `BANK_KEY_ID`
- `BANK_KEY_MAPPING_JSON` (JSON map from bank key ID to Vault key name)
- `VAULT_PUBLIC_KEY_CACHE_TTL_SECONDS`

### Auth and Security

- `JWT_ISSUER`
- `JWT_AUDIENCE`
- `NONCE_WINDOW_SECONDS`

### Performance / Metrics

- `PROVER_MAX_PARALLEL_PROOFS`
- `WORKER_METRICS_PORT`
- `NATIVE_VERIFY_BASELINE_SECONDS`

## Local Development Defaults

The docker-compose stack sets sane local defaults for all critical variables. For non-Docker execution, use `.env.example` as baseline.

## Best Practices

- Keep `BANK_KEY_MAPPING_JSON` minimal and explicit.
- Rotate Vault Transit keys by version, then update key mapping and rollout gradually.
- Keep `NONCE_WINDOW_SECONDS` tight in production.
- Set `PROVER_MAX_PARALLEL_PROOFS` based on CPU and proving artifact size, not by guesswork.
