from __future__ import annotations

import hashlib
import json
import os
import time
from pathlib import Path
from typing import Any
from uuid import uuid4

import httpx
from fastapi import FastAPI
from fastapi.responses import HTMLResponse
from pydantic import BaseModel

from vellum_core.auth import VaultJWTSigner
from vellum_core.errors import APIError, register_exception_handlers
from vellum_core.vault import VaultTransitClient


class DemoBatchProveRequest(BaseModel):
    balances: list[int] | None = None
    limits: list[int] | None = None
    source_ref: str | None = None


class DemoVerifyRequest(BaseModel):
    circuit_id: str
    proof: dict[str, Any]
    public_signals: list[Any]


class DashboardConfig:
    def __init__(self) -> None:
        self.prover_url = os.getenv("PROVER_URL", "http://prover:8001")
        self.verifier_url = os.getenv("VERIFIER_URL", "http://verifier:8002")
        self.jwt_issuer = os.getenv("JWT_ISSUER", "bank.local")
        self.jwt_audience = os.getenv("JWT_AUDIENCE", "sentinel-zk")
        self.bank_key_id = os.getenv("BANK_KEY_ID", "bank-key-1")
        self.circuits_dir = Path(os.getenv("CIRCUITS_DIR", "/app/circuits"))

        self.vault_addr = os.getenv("VAULT_ADDR", "http://vault:8200")
        self.vault_token = os.getenv("VAULT_TOKEN", "root")
        self.vault_jwt_key = os.getenv("VELLUM_JWT_KEY", "vellum-jwt")
        self.vault_bank_key = os.getenv("VELLUM_BANK_KEY", "vellum-bank")


config = DashboardConfig()
vault_client = VaultTransitClient(addr=config.vault_addr, token=config.vault_token)
jwt_signer = VaultJWTSigner(
    vault_client=vault_client,
    key_name=config.vault_jwt_key,
    issuer=config.jwt_issuer,
    audience=config.jwt_audience,
)

app = FastAPI(title="Vellum Dashboard", version="3.0.0")
register_exception_handlers(app)


async def _jwt_token() -> str:
    return await jwt_signer.sign(subject="dashboard-demo-user")


async def _handshake_headers(method: str, path: str, body: bytes) -> dict[str, str]:
    ts = str(int(time.time()))
    nonce = str(uuid4())
    body_hash = hashlib.sha256(body).hexdigest()
    canonical = f"{method}\n{path}\n{ts}\n{nonce}\n{body_hash}".encode("utf-8")
    signature = await vault_client.sign(config.vault_bank_key, canonical)
    return {
        "X-Bank-Key-Id": config.bank_key_id,
        "X-Bank-Timestamp": ts,
        "X-Bank-Nonce": nonce,
        "X-Bank-Signature": signature.encoded,
    }


def _load_circuits() -> list[dict[str, Any]]:
    result: list[dict[str, Any]] = []
    if not config.circuits_dir.exists():
        return result
    for folder in sorted(config.circuits_dir.iterdir()):
        if not folder.is_dir():
            continue
        manifest_path = folder / "manifest.json"
        if not manifest_path.exists():
            continue
        manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
        result.append(manifest)
    return result


def _upstream_error(service: str, response: httpx.Response) -> APIError:
    details: dict[str, Any] = {"service": service, "status_code": response.status_code}
    try:
        details["response"] = response.json()
    except Exception:
        details["response"] = response.text
    return APIError(
        status_code=response.status_code,
        code="upstream_error",
        message=f"{service} request failed",
        details=details,
    )


@app.get("/", response_class=HTMLResponse)
async def dashboard() -> HTMLResponse:
    return HTMLResponse(
        """
<!doctype html>
<html lang="en">
<head>
  <meta charset="utf-8" />
  <meta name="viewport" content="width=device-width, initial-scale=1" />
  <title>Vellum Dashboard</title>
  <style>
    body { font-family: ui-sans-serif, system-ui, sans-serif; margin: 0; background: #f5f8f7; color: #173b2f; }
    main { max-width: 980px; margin: 0 auto; padding: 24px; }
    .card { background: #fff; border: 1px solid #d7e2dc; border-radius: 12px; padding: 14px; margin-bottom: 14px; }
    textarea, input, button { width: 100%; box-sizing: border-box; border: 1px solid #cad8d0; border-radius: 8px; padding: 8px; }
    textarea { min-height: 140px; font-family: ui-monospace, SFMono-Regular, Menlo, monospace; }
    button { background: #1f6b4d; color: #fff; border: none; cursor: pointer; font-weight: 600; }
    button.secondary { background: #44685a; }
    pre { background: #0f1d16; color: #d8f5e7; border-radius: 8px; padding: 10px; overflow: auto; }
    .grid { display: grid; grid-template-columns: 1fr 1fr; gap: 14px; }
    @media (max-width: 880px) { .grid { grid-template-columns: 1fr; } }
  </style>
</head>
<body>
  <main>
    <h1>Vellum Protocol Dashboard</h1>

    <div class="card">
      <h3>Vellum Trust-Speedup</h3>
      <div id="speed">Loading...</div>
      <button id="refreshSpeed" class="secondary" style="margin-top:8px;">Refresh Speedup</button>
    </div>

    <div class="grid">
      <section class="card">
        <h3>Create Batch Proof</h3>
        <p>Provide direct arrays or <code>source_ref</code>.</p>
        <textarea id="batchInput">{
  "balances": [120, 220, 330],
  "limits": [100, 200, 300]
}</textarea>
        <button id="proveBtn">Start Batch Proof Job</button>
        <div id="proveStatus" style="margin-top:8px;">Idle</div>
      </section>

      <section class="card">
        <h3>Verify Last Proof</h3>
        <input id="proofId" readonly />
        <button id="verifyBtn" class="secondary" disabled style="margin-top:8px;">Verify Last Completed Proof</button>
        <div id="verifyStatus" style="margin-top:8px;">Idle</div>
      </section>
    </div>

    <div class="card">
      <h3>Payload</h3>
      <pre id="payload">No data yet.</pre>
    </div>
  </main>

  <script>
    const batchInput = document.getElementById("batchInput");
    const proveBtn = document.getElementById("proveBtn");
    const proveStatus = document.getElementById("proveStatus");
    const verifyBtn = document.getElementById("verifyBtn");
    const verifyStatus = document.getElementById("verifyStatus");
    const payload = document.getElementById("payload");
    const proofIdInput = document.getElementById("proofId");
    const speed = document.getElementById("speed");
    const refreshSpeed = document.getElementById("refreshSpeed");

    let latestCompleted = null;
    let polling = null;

    function show(data) { payload.textContent = JSON.stringify(data, null, 2); }

    async function loadSpeed() {
      const res = await fetch('/api/trust-speed');
      const body = await res.json();
      if (!res.ok) {
        speed.textContent = `Speedup unavailable: ${body?.error?.message || res.statusText}`;
        return;
      }
      const native = body.native_verify_ms != null ? body.native_verify_ms.toFixed(6) : 'n/a';
      const zk = body.zk_batch_verify_ms != null ? body.zk_batch_verify_ms.toFixed(6) : 'n/a';
      const ratio = body.trust_speedup != null ? `${body.trust_speedup.toFixed(6)}x` : 'n/a';
      speed.textContent = `Native: ${native} ms | ZK-Batch: ${zk} ms | Trust-Speedup: ${ratio}`;
    }

    async function poll(proofId) {
      if (polling) clearInterval(polling);
      polling = setInterval(async () => {
        const res = await fetch(`/api/demo/proofs/${proofId}`);
        const body = await res.json();
        if (!res.ok) {
          proveStatus.textContent = `Polling failed: ${body?.error?.message || res.statusText}`;
          clearInterval(polling);
          return;
        }
        proveStatus.textContent = `Proof ${proofId}: ${body.status}`;
        show(body);
        if (body.status === 'completed') {
          latestCompleted = body;
          verifyBtn.disabled = false;
          clearInterval(polling);
        }
        if (body.status === 'failed') {
          verifyBtn.disabled = true;
          clearInterval(polling);
        }
      }, 1500);
    }

    proveBtn.addEventListener('click', async () => {
      verifyBtn.disabled = true;
      latestCompleted = null;
      let parsed;
      try { parsed = JSON.parse(batchInput.value); }
      catch (e) {
        proveStatus.textContent = `Invalid JSON: ${e.message}`;
        return;
      }

      const res = await fetch('/api/demo/prove', {
        method: 'POST',
        headers: {'Content-Type': 'application/json'},
        body: JSON.stringify(parsed),
      });
      const body = await res.json();
      show(body);
      if (!res.ok) {
        proveStatus.textContent = `Submit failed: ${body?.error?.message || res.statusText}`;
        return;
      }
      proofIdInput.value = body.proof_id;
      proveStatus.textContent = `Proof ${body.proof_id}: queued`;
      poll(body.proof_id);
    });

    verifyBtn.addEventListener('click', async () => {
      if (!latestCompleted?.proof) {
        verifyStatus.textContent = 'No completed proof available';
        return;
      }
      const res = await fetch('/api/demo/verify', {
        method: 'POST',
        headers: {'Content-Type': 'application/json'},
        body: JSON.stringify({
          circuit_id: latestCompleted.circuit_id,
          proof: latestCompleted.proof,
          public_signals: latestCompleted.public_signals,
        }),
      });
      const body = await res.json();
      show(body);
      if (!res.ok) {
        verifyStatus.textContent = `Verify failed: ${body?.error?.message || res.statusText}`;
        return;
      }
      verifyStatus.textContent = `Verification: ${body.valid ? 'VALID' : 'INVALID'} (${body.verification_ms.toFixed(2)} ms)`;
      loadSpeed().catch(() => {});
    });

    refreshSpeed.addEventListener('click', () => loadSpeed());
    loadSpeed().catch((e) => { speed.textContent = e.message; });
  </script>
</body>
</html>
        """
    )


@app.get("/healthz")
async def healthz() -> dict[str, str]:
    return {"status": "ok"}


@app.get("/api/circuits")
async def list_circuits() -> dict[str, Any]:
    return {"circuits": _load_circuits()}


@app.post("/api/demo/prove")
async def demo_prove(payload: DemoBatchProveRequest) -> dict[str, Any]:
    body = payload.model_dump_json(exclude_none=True).encode("utf-8")
    token = await _jwt_token()
    path = "/v1/proofs/batch"
    headers = {
        "Authorization": f"Bearer {token}",
        "Content-Type": "application/json",
        **(await _handshake_headers("POST", path, body)),
    }
    async with httpx.AsyncClient(timeout=60.0) as client:
        response = await client.post(f"{config.prover_url}{path}", content=body, headers=headers)
    if response.status_code != 202:
        raise _upstream_error("prover", response)
    return response.json()


@app.get("/api/demo/proofs/{proof_id}")
async def demo_proof_status(proof_id: str) -> dict[str, Any]:
    token = await _jwt_token()
    path = f"/v1/proofs/{proof_id}"
    headers = {"Authorization": f"Bearer {token}"}
    async with httpx.AsyncClient(timeout=30.0) as client:
        response = await client.get(f"{config.prover_url}{path}", headers=headers)
    if response.status_code != 200:
        raise _upstream_error("prover", response)
    return response.json()


@app.post("/api/demo/verify")
async def demo_verify(payload: DemoVerifyRequest) -> dict[str, Any]:
    token = await _jwt_token()
    path = "/v1/verify"
    headers = {"Authorization": f"Bearer {token}", "Content-Type": "application/json"}
    async with httpx.AsyncClient(timeout=60.0) as client:
        response = await client.post(
            f"{config.verifier_url}{path}",
            content=payload.model_dump_json(),
            headers=headers,
        )
    if response.status_code != 200:
        raise _upstream_error("verifier", response)
    return response.json()


@app.get("/api/trust-speed")
async def demo_trust_speed() -> dict[str, Any]:
    token = await _jwt_token()
    path = "/v1/trust-speed"
    headers = {"Authorization": f"Bearer {token}"}
    async with httpx.AsyncClient(timeout=30.0) as client:
        response = await client.get(f"{config.verifier_url}{path}", headers=headers)
    if response.status_code != 200:
        raise _upstream_error("verifier", response)
    return response.json()


if __name__ == "__main__":
    import uvicorn

    uvicorn.run("dashboard_service:app", host="0.0.0.0", port=8000, reload=False)
