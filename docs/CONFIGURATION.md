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
- `POLICY_PACKS_DIR` (default: `<cwd>/policy_packs`)
- `SHARED_ASSETS_DIR` (default: `<cwd>/shared_assets`)
- `PROOF_OUTPUT_DIR` (default: `<shared_assets>/proofs`)
- `SNARKJS_BIN` (default: `snarkjs`)
- `SETUP_CIRCUIT_IDS` (optional, bootstrap filter for `setup_framework.sh`; comma-separated)

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

- `SECURITY_PROFILE` (`strict` or `dev`; default: `strict`)
- `JWT_ISSUER`
- `JWT_AUDIENCE`
- `NONCE_WINDOW_SECONDS`
- `JWT_MAX_TTL_SECONDS`
- `JWT_LEEWAY_SECONDS`
- `SUBMIT_RATE_LIMIT_PER_MINUTE`
- `METRICS_REQUIRE_AUTH`
- `VELLUM_DATA_KEY` (Vault Transit key for encrypted job payload persistence)
- `TLS_CA_BUNDLE` (optional custom CA bundle path for outbound TLS verification)

### Performance / Metrics

- `PROVER_MAX_PARALLEL_PROOFS`
- `WORKER_METRICS_HOST`
- `WORKER_METRICS_PORT`
- `NATIVE_VERIFY_BASELINE_SECONDS`
- `PROOF_PROVIDER_MODE` (`grpc` only; default: `grpc`)
- `GRPC_PROVER_ENDPOINT` (default: `127.0.0.1:50051`)
- `GRPC_PROVER_TIMEOUT_SECONDS` (default: `30`)
- `PROOF_SHADOW_MODE` (runtime no longer supports shadow mode; must remain `false`)
- `PROOF_SHADOW_PROVIDER_MODE` (runtime must remain `grpc`)
- `PROOF_SHADOW_COMPARE_PUBLIC_SIGNALS` (ignored in grpc-only runtime)
- `GRPC_CUTOVER_GATE_ENFORCED` (benchmark/regression helper; runtime no longer gates startup on this)
- `GRPC_CUTOVER_GATE_REPORT_PATH` (benchmark/regression helper path)
- `NATIVE_GENERATE_BACKEND` (`snarkjs` or `rapidsnark`; native-prover service, default: `snarkjs`)
- `NATIVE_WITNESS_BACKEND` (`snarkjs` or `binary`; native-prover service, default: `snarkjs`)
- `WITNESS_GEN_BIN` (native-prover service witness binary, default: `witnesscalc`)
- `RAPIDSNARK_BIN` (native-prover service prove binary, default: `rapidsnark`)
- `GATE_GRPC_MODE` (`snarkjs`, `rapidsnark`, or `auto`; benchmark script gate-source selection, default: `snarkjs`)
- `SHADOW_NATIVE_GENERATE_BACKEND` (`snarkjs` or `rapidsnark`; benchmark script shadow-mode native generate backend, default: `snarkjs` or auto-`rapidsnark` when `ENABLE_RAPIDSNARK=1` and `GATE_GRPC_MODE!=snarkjs`)
- `JOB_RUNTIME_RETENTION_DAYS` (default: `7`; prune terminal job runtime payload columns)
- `FILE_ARCHIVE_AFTER_DAYS` (default: `30`; archive aged proof/evidence files)
- `MAINTENANCE_INTERVAL_SECONDS` (default: `3600`; maintenance worker cycle)
- `MAINTENANCE_CYCLE_FILE_SCAN_LIMIT` (default: `1000`; max files/jobs per maintenance cycle)

### Observability / Logging

- `LOG_LEVEL` (default `INFO`)
- `OTEL_ENABLED` (`true` or `false`, default `true`)
- `OTEL_EXPORTER_OTLP_ENDPOINT` (default: `http://otel-collector:4317`)
- `OTEL_EXPORTER_OTLP_INSECURE` (`true` or `false`, default `true`)
- `OTEL_FASTAPI_EXCLUDED_URLS` (default: `/healthz,/metrics`)
- `OTEL_SERVICE_NAMESPACE` (default: `vellum-core`)
- `ENVIRONMENT` (default: `dev`)

## Local Development Defaults

The docker-compose stack sets sane local defaults for all critical variables. For non-Docker execution, use `.env.example` as baseline.

## Best Practices

- Keep `BANK_KEY_MAPPING_JSON` minimal and explicit.
- Use `SECURITY_PROFILE=dev` only for local/non-production runs.
- Rotate Vault Transit keys by version, then update key mapping and rollout gradually.
- Keep `NONCE_WINDOW_SECONDS` tight in production.
- Keep `JWT_MAX_TTL_SECONDS` low (for example <= 900) and require scopes per endpoint.
- Set `PROVER_MAX_PARALLEL_PROOFS` based on CPU and proving artifact size, not by guesswork.
