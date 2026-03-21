# API Reference

All error responses follow:

```json
{
  "error": {
    "code": "string",
    "message": "string",
    "details": {}
  }
}
```

## Authentication

### JWT (Bearer)

Protected routes require `Authorization: Bearer <token>`.
JWTs must include: `iss`, `aud`, `sub`, `iat`, `nbf`, `exp`, `jti`.
Tokens exceeding configured `JWT_MAX_TTL_SECONDS` are rejected.

Required scopes:

- prover submit/verify routes: `proofs:write`
- prover read routes + circuits: `proofs:read`
- audit/trust routes: `audit:read`

### Bank Handshake (prover create route)

`POST /v1/proofs/batch` also requires:

- `X-Bank-Key-Id`
- `X-Bank-Timestamp`
- `X-Bank-Nonce`
- `X-Bank-Signature`

Canonical signature string:

`<METHOD>\n<PATH>\n<TIMESTAMP>\n<NONCE>\n<SHA256(body)>`

## Prover Service (`:8001`)

- `GET /healthz`
- `GET /metrics`
- `POST /v1/proofs/batch`
- `GET /v1/proofs/{proof_id}`
- `GET /v1/proofs?status=&circuit_id=&limit=`

### `POST /v1/proofs/batch`

Request (`BatchProveRequest`):

- `circuit_id` (default: `batch_credit_check`)
- one of:
  - `balances` + `limits`
  - `private_input`

Response:

```json
{ "proof_id": "uuid", "status": "queued" }
```

Possible additional failures:

- `429 rate_limited` when submit rate limit is exceeded.

## Verifier Service (`:8002`)

- `GET /healthz`
- `GET /metrics`
- `POST /v1/verify`
- `GET /v1/circuits`
- `GET /v1/audit/verify-chain`
- `GET /v1/trust-speed`

### `POST /v1/verify`

Request:

```json
{
  "circuit_id": "batch_credit_check",
  "proof": {},
  "public_signals": []
}
```

Response:

```json
{
  "valid": true,
  "verified_at": "2026-01-01T00:00:00Z",
  "verification_ms": 12.34
}
```

## Dashboard Service (`:8000`)

UI route:

- `GET /`

Health:

- `GET /healthz`

Framework aggregation:

- `GET /api/framework/health`
- `GET /api/framework/diagnostics`
- `GET /api/framework/overview`
- `GET /api/framework/circuits`
- `GET /api/framework/audit-chain`

Demo flow proxies:

- `POST /api/demo/prove`
- `GET /api/demo/proofs/{proof_id}`
- `GET /api/demo/proofs?status=&circuit_id=&limit=`
- `POST /api/demo/verify`
- `GET /api/trust-speed`
- `GET /api/circuits`

## Metrics Authentication

By default (`METRICS_REQUIRE_AUTH=true`), prover and verifier `/metrics`
require bearer JWT with matching read scope.

## Status Model

Proof job lifecycle:

- `queued`
- `running`
- `completed`
- `failed`

Operational recommendation: treat `failed` as terminal, re-enqueue via a new request instead of mutating failed jobs.
