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

Required scopes:

- policy/proof write routes: `proofs:write`
- proof/status and circuits routes: `proofs:read`
- audit/attestation/trust routes: `audit:read`

### Bank Handshake (submit routes)

`POST /v1/proofs/batch` and `POST /v5/policy-runs` require signed anti-replay headers:

- `X-Bank-Key-Id`
- `X-Bank-Timestamp`
- `X-Bank-Nonce`
- `X-Bank-Signature`

Canonical signature string:

`<METHOD>\n<PATH>\n<TIMESTAMP>\n<NONCE>\n<SHA256(body)>`

## Contract and Gate Policy

- v5 request/response schemas are guarded by snapshot-backed contract tests (`pytest -m contract`).
- Security-sensitive behavior is guarded by regression tests (`pytest -m security`).
- v1 endpoints remain available as legacy interfaces and emit deprecation/sunset headers.

## v5 Primary Surface

### Prover Service (`:8001`)

- `POST /v5/policy-runs`
- `GET /v5/policy-runs/{run_id}`

#### `POST /v5/policy-runs`

Request:

```json
{
  "policy_id": "lending_risk_v1",
  "evidence_payload": {
    "balances": [120],
    "limits": [100]
  },
  "context": {
    "tenant": "acme-bank"
  }
}
```

Alternative request (evidence by reference):

```json
{
  "policy_id": "lending_risk_v1",
  "evidence_ref": "memory://run-123-evidence",
  "context": {
    "tenant": "acme-bank"
  }
}
```

Validation rules:

- provide `evidence_payload` or `evidence_ref`
- `policy_id` must exist in the policy registry

Response (202):

```json
{
  "run_id": "uuid",
  "policy_id": "lending_risk_v1",
  "status": "queued",
  "attestation_id": "att-uuid"
}
```

#### `GET /v5/policy-runs/{run_id}`

Response:

```json
{
  "run_id": "uuid",
  "policy_id": "lending_risk_v1",
  "status": "completed",
  "circuit_id": "batch_credit_check",
  "decision": "pass",
  "attestation_id": "att-uuid",
  "evidence_ref": "memory://run-123-evidence",
  "metadata": {
    "policy_version": "1.0.0"
  }
}
```

### Verifier Service (`:8002`)

- `GET /v5/attestations/{attestation_id}`

#### `GET /v5/attestations/{attestation_id}`

Response:

```json
{
  "attestation_id": "att-uuid",
  "run_id": "uuid",
  "policy_id": "lending_risk_v1",
  "policy_version": "1.0.0",
  "circuit_id": "batch_credit_check",
  "decision": "pass",
  "proof_hash": "sha256...",
  "public_signals_hash": "sha256...",
  "artifact_digests": {
    "wasm_sha256": "...",
    "zkey_sha256": "...",
    "verification_key_sha256": "..."
  },
  "signature_chain": [
    {
      "audit_id": 1,
      "entry_hash": "...",
      "signature": "vault:v1:..."
    }
  ]
}
```

## v5 Error Codes

Common v5 domain errors:

- `unknown_policy`
- `unknown_run_id`
- `invalid_evidence_ref`
- `unknown_attestation_id`
- `attestation_not_ready`
- `payload_too_large` (HTTP 413 when request body exceeds configured limit)
- `invalid_private_input_schema` (HTTP 422 when `private_input` violates circuit `input_schema`)

## v1 Legacy Surface

v1 remains available for transition and now emits deprecation metadata:

- `Deprecation: true`
- `Sunset: Tue, 30 Sep 2026 00:00:00 GMT`

Legacy routes:

- Prover: `POST /v1/proofs/batch`, `GET /v1/proofs/{proof_id}`, `GET /v1/proofs`
- Verifier: `POST /v1/verify`, `GET /v1/circuits`, `GET /v1/audit/verify-chain`, `GET /v1/trust-speed`

## Metrics

By default (`METRICS_REQUIRE_AUTH=true`), prover and verifier `/metrics` endpoints
require a bearer token with matching read scope.
