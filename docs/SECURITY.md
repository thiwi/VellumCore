# Security Model

## Authentication Layers

### 1) JWT authentication

All protected service routes require bearer JWTs signed by Vault Transit Ed25519 keys.

Validation checks:

- issuer (`iss`)
- audience (`aud`)
- required claims (`sub`, `iat`, `exp`)

### 2) Bank request handshake (prover submit)

`POST /v1/proofs/batch` requires signed anti-replay headers.

- Signature covers method, path, timestamp, nonce, and body hash.
- Signature key is resolved through `BANK_KEY_MAPPING_JSON`.
- Nonces are checked/stored in Redis with expiry (`NONCE_WINDOW_SECONDS`).

## Audit Integrity

Every key lifecycle event is appended to `audit_log` with signature and hash chaining.

- `VellumAuditStore` signs entries with Vault Transit.
- `VellumIntegrityService.verify_chain()` checks hash continuity and signatures.

## Hardening Recommendations

- Replace dev Vault token and run non-dev Vault in production.
- Restrict network access to prover/verifier/dashboard ingress points.
- Use short JWT TTL and rotate signing keys regularly.
- Protect Redis and Postgres with network policy and credentials.
- Monitor repeated `nonce_replay`, `invalid_token`, and `invalid_handshake_signature` errors.

## Sensitive Data Handling

- Private inputs are handled inside proof generation paths; avoid logging raw private payloads.
- Do not expose proof internals or private inputs in public logs/dashboards.
- Keep `shared_assets` and generated proof output storage permission-scoped.
