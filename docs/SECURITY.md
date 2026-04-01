# Security Model

## Authentication Layers

### 1) JWT authentication

All protected service routes require bearer JWTs signed by Vault Transit Ed25519 keys.

Validation checks:

- issuer (`iss`)
- audience (`aud`)
- required claims (`sub`, `iat`, `nbf`, `exp`, `jti`)
- max token lifetime (`JWT_MAX_TTL_SECONDS`)
- scope enforcement per route (`proofs:write`, `proofs:read`, `audit:read`)
- admin scope enforcement for DLQ operations (`ops:read`, `ops:write`)
- dashboard API scope enforcement (`dashboard:read`, `dashboard:write`) when
  `DASHBOARD_REQUIRE_AUTH=true` (default)

### 2) Bank request handshake (prover submit)

`POST /v6/proofs/batch` and `POST /v6/runs` require signed anti-replay headers.

- Signature covers method, path, timestamp, nonce, and body hash.
- Signature key is resolved through `BANK_KEY_MAPPING_JSON`.
- Nonces are checked/stored in Redis with expiry (`NONCE_WINDOW_SECONDS`).
- Submit requests are rate-limited in Redis (`SUBMIT_RATE_LIMIT_PER_MINUTE`).
- Submit request bodies are size-limited (`MAX_SUBMIT_BODY_BYTES`).
- Dashboard demo proxy body is size-limited (`DASHBOARD_MAX_DEMO_PROVE_BODY_BYTES`).
- Dashboard API auth can be temporarily bypassed only via
  `DASHBOARD_REQUIRE_AUTH=false` (intended for local/e2e compatibility).

## Audit Integrity

Every key lifecycle event is appended to `audit_log` with signature and hash chaining.

- `VellumAuditStore` signs entries with Vault Transit.
- `VellumIntegrityService.verify_chain()` checks hash continuity and signatures.

## Hardening Recommendations

- Use `SECURITY_PROFILE=strict` in production; `SECURITY_PROFILE=dev` only for local stacks.
- Replace dev Vault token and run non-dev Vault in production.
- Restrict network access to prover/verifier/dashboard ingress points.
- Use short JWT TTL and rotate signing keys regularly.
- Protect Redis and Postgres with network policy and credentials.
- Monitor repeated `nonce_replay`, `invalid_token`, and `invalid_handshake_signature` errors.
- Monitor `payload_too_large` and `invalid_private_input_schema` spikes as potential DoS probing.

## Sensitive Data Handling

- Incoming request payloads and private inputs are persisted encrypted as `sealed_job_payload`.
- Worker decrypts payload only during execution and purges sealed payload after terminal status.
- `input_fingerprint` and `input_summary` keep non-sensitive traceability for operations.
- Security-relevant auth/rate/decrypt events are written to `security_events`.
- Do not expose proof internals or private inputs in public logs/dashboards.
- OTEL collector pipeline should drop sensitive attributes (`db.statement`, request/response bodies, auth headers).
- Keep `shared_assets` and generated proof output storage permission-scoped.
