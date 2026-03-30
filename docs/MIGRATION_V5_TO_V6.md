# Migration: v5 to v6

v6 introduces a resource-oriented run surface and removes v1/v5 HTTP routes.

## Breaking changes summary

- Removed HTTP routes:
  - all `/v1/*` service routes
  - all `/v5/*` policy-run and attestation routes
- Added v6 primary routes:
  - `POST /v6/runs`
  - `GET /v6/runs/{run_id}`
  - `GET /v6/runs/{run_id}/attestation`

## Endpoint mapping

| v5 | v6 |
|---|---|
| `POST /v5/policy-runs` | `POST /v6/runs` |
| `GET /v5/policy-runs/{run_id}` | `GET /v6/runs/{run_id}` |
| `GET /v5/attestations/{attestation_id}` | `GET /v6/runs/{run_id}/attestation` |

Supporting route namespace updates:

| v1 | v6 |
|---|---|
| `POST /v1/proofs/batch` | `POST /v6/proofs/batch` |
| `GET /v1/proofs/{proof_id}` | `GET /v6/proofs/{proof_id}` |
| `GET /v1/proofs` | `GET /v6/proofs` |
| `POST /v1/verify` | `POST /v6/verify` |
| `GET /v1/circuits` | `GET /v6/circuits` |
| `GET /v1/audit/verify-chain` | `GET /v6/audit/verify-chain` |
| `GET /v1/trust-speed` | `GET /v6/trust-speed` |

## Request/response mapping

### Create run request

v5:

```json
{
  "policy_id": "lending_risk_v1",
  "evidence_payload": {"balances": [120], "limits": [100]},
  "context": {"tenant": "acme-bank"},
  "request_id": "client-123"
}
```

v6 (inline evidence):

```json
{
  "policy_id": "lending_risk_v1",
  "evidence": {"type": "inline", "payload": {"balances": [120], "limits": [100]}},
  "context": {"tenant": "acme-bank"},
  "client_request_id": "client-123"
}
```

v6 (reference evidence):

```json
{
  "policy_id": "lending_risk_v1",
  "evidence": {"type": "ref", "ref": "memory://run-123-evidence"}
}
```

### Run status response

- `status` renamed to `lifecycle_state`.
- free-form `metadata` removed from response.
- typed `error` object added.
- `submitted_at` replaces `created_at`.

### Attestation response

- policy fields moved from flat shape to nested object:
  - v5: `policy_id`, `policy_version`
  - v6: `policy: { id, version }`
- attestation lookup now keys by `run_id` path segment.

## Error-code migration

- `unknown_attestation_id` is replaced by `unknown_run_id` for v6 attestation path lookups.
- Existing codes retained where semantic meaning is unchanged:
  - `unknown_policy`
  - `invalid_evidence_ref`
  - `attestation_not_ready`
  - `payload_too_large`
  - `invalid_private_input_schema`

## Dashboard proxy mapping

- `/api/v5/policy-runs` -> `/api/v6/runs`
- `/api/v5/policy-runs/{run_id}` -> `/api/v6/runs/{run_id}`
- `/api/v5/attestations/{attestation_id}` -> `/api/v6/runs/{run_id}/attestation`

## Rollout checklist

1. Update client path prefixes from `/v1` or `/v5` to `/v6`.
2. Migrate run-create payloads to typed `evidence` discriminated union.
3. Update response parsing for `lifecycle_state`, nested `policy`, and typed `error`.
4. Re-run contract tests and integration tests.
5. Validate downstream analytics/parsers no longer depend on removed response `metadata`.
