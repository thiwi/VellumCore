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

- write routes: `proofs:write`
- read routes for proof/circuit status: `proofs:read`
- read routes for audit/trust/attestation: `audit:read`
- admin DLQ read routes: `ops:read`
- admin DLQ mutation routes: `ops:write`

### Bank Handshake (submit routes)

`POST /v6/proofs/batch` and `POST /v6/runs` require signed anti-replay headers:

- `X-Bank-Key-Id`
- `X-Bank-Timestamp`
- `X-Bank-Nonce`
- `X-Bank-Signature`

Canonical signature string:

`<METHOD>\n<PATH>\n<TIMESTAMP>\n<NONCE>\n<SHA256(body)>`

## Contract and Gate Policy

- v6 request/response schemas are guarded by snapshot-backed contract tests (`pytest -m contract`).
- Security-sensitive behavior is guarded by regression tests (`pytest -m security`).
- v1 and v5 HTTP routes have been removed in v6.

## v6 Primary Surface

### Prover Service (`:8001`)

- `POST /v6/runs`
- `GET /v6/runs/{run_id}`

#### `POST /v6/runs`

Request (inline evidence):

```json
{
  "policy_id": "lending_risk_v1",
  "policy_params_ref": "bank_profile_q2",
  "evidence": {
    "type": "inline",
    "payload": {
      "balances": [120],
      "limits": [100]
    }
  },
  "context": {
    "tenant": "acme-bank"
  },
  "client_request_id": "run-2026-03-30-001"
}
```

Request (evidence reference):

```json
{
  "policy_id": "lending_risk_v1",
  "evidence": {
    "type": "ref",
    "ref": "memory://run-123-evidence"
  }
}
```

Response (202):

```json
{
  "run_id": "uuid",
  "policy_id": "lending_risk_v1",
  "lifecycle_state": "queued",
  "attestation_id": "att-uuid"
}
```

#### `GET /v6/runs/{run_id}`

Response:

```json
{
  "run_id": "uuid",
  "policy_id": "lending_risk_v1",
  "lifecycle_state": "completed",
  "circuit_id": "batch_credit_check",
  "decision": "pass",
  "attestation_id": "att-uuid",
  "evidence_ref": "memory://run-123-evidence",
  "policy_params_ref": "bank_profile_q2",
  "policy_params_hash": "sha256...",
  "client_request_id": "run-2026-03-30-001",
  "context": {
    "tenant": "acme-bank"
  },
  "error": null,
  "submitted_at": "2026-03-30T09:00:00Z",
  "updated_at": "2026-03-30T09:00:12Z"
}
```

### Verifier Service (`:8002`)

- `GET /v6/runs/{run_id}/attestation`

#### `GET /v6/runs/{run_id}/attestation`

Response:

```json
{
  "attestation_id": "att-uuid",
  "run_id": "uuid",
  "policy": {
    "id": "lending_risk_v1",
    "version": "1.0.0"
  },
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
  ],
  "metadata": {
    "policy_params_ref": "bank_profile_q2",
    "policy_params_hash": "sha256..."
  }
}
```

## v6 Supporting Surface

- Prover: `POST /v6/proofs/batch`, `GET /v6/proofs/{proof_id}`, `GET /v6/proofs`
- Prover admin ops: `GET /v6/ops/dlq`, `POST /v6/ops/dlq/{dlq_id}/requeue`
- Verifier: `POST /v6/verify`, `GET /v6/circuits`, `GET /v6/audit/verify-chain`, `GET /v6/trust-speed`

## v6 Error Codes

Common domain errors:

- `unknown_policy`
- `unknown_run_id`
- `invalid_evidence_ref`
- `attestation_not_ready`
- `payload_too_large` (HTTP 413)
- `invalid_private_input_schema` (HTTP 422)

Failed run status responses may include structured explainability under:

- `error.details.explainability` (rule mapping + provider hint when available)

## Metrics

By default (`METRICS_REQUIRE_AUTH=true`), prover and verifier `/metrics` endpoints
require a bearer token with matching read scope.
