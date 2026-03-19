from __future__ import annotations

import base64
import hashlib
import json
import os
import time
from pathlib import Path
from typing import Any
from uuid import uuid4

import httpx
import jwt
from cryptography.hazmat.primitives import hashes
from cryptography.hazmat.primitives.asymmetric import padding
from cryptography.hazmat.primitives.serialization import load_pem_private_key
from fastapi import FastAPI
from fastapi.responses import HTMLResponse
from pydantic import BaseModel

from sentinel_zk.errors import APIError, register_exception_handlers


class DemoProveRequest(BaseModel):
    circuit_id: str
    private_input: dict[str, Any]


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
        self.jwt_private_key_path = Path(
            os.getenv("JWT_PRIVATE_KEY_PATH", "/app/config/dev_jwt_private.pem")
        )
        self.bank_private_key_path = Path(
            os.getenv("BANK_PRIVATE_KEY_PATH", "/app/config/dev_bank_private.pem")
        )


config = DashboardConfig()
app = FastAPI(title="Sentinel-ZK Dashboard", version="1.0.0")
register_exception_handlers(app)


def _jwt_token() -> str:
    now = int(time.time())
    claims = {
        "iss": config.jwt_issuer,
        "aud": config.jwt_audience,
        "sub": "dashboard-demo-user",
        "iat": now,
        "exp": now + 3600,
    }
    key = config.jwt_private_key_path.read_text(encoding="utf-8")
    return jwt.encode(claims, key, algorithm="RS256")


def _handshake_headers(method: str, path: str, body: bytes) -> dict[str, str]:
    ts = str(int(time.time()))
    nonce = str(uuid4())
    body_hash = hashlib.sha256(body).hexdigest()
    canonical = f"{method}\n{path}\n{ts}\n{nonce}\n{body_hash}"
    private_key_pem = config.bank_private_key_path.read_bytes()
    private_key = load_pem_private_key(private_key_pem, password=None)
    signature = private_key.sign(
        canonical.encode("utf-8"),
        padding.PKCS1v15(),
        hashes.SHA256(),
    )
    signature_b64 = base64.b64encode(signature).decode("utf-8")
    return {
        "X-Bank-Key-Id": config.bank_key_id,
        "X-Bank-Timestamp": ts,
        "X-Bank-Nonce": nonce,
        "X-Bank-Signature": signature_b64,
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
  <title>Sentinel-ZK Dashboard</title>
  <link rel="preconnect" href="https://fonts.googleapis.com">
  <link rel="preconnect" href="https://fonts.gstatic.com" crossorigin>
  <link href="https://fonts.googleapis.com/css2?family=Space+Grotesk:wght@400;500;700&family=IBM+Plex+Mono:wght@400;500&display=swap" rel="stylesheet">
  <style>
    :root {
      --bg: #f2f4ef;
      --card: #ffffff;
      --ink: #132a13;
      --muted: #4f6b4f;
      --accent: #2d6a4f;
      --accent-2: #95d5b2;
      --danger: #9b2226;
      --radius: 14px;
    }
    * { box-sizing: border-box; }
    body {
      margin: 0;
      font-family: "Space Grotesk", sans-serif;
      color: var(--ink);
      background:
        radial-gradient(circle at 90% 10%, #d8f3dc 0, #d8f3dc 18%, transparent 18%),
        radial-gradient(circle at 12% 88%, #b7e4c7 0, #b7e4c7 20%, transparent 20%),
        var(--bg);
      min-height: 100vh;
    }
    .wrap {
      max-width: 1080px;
      margin: 0 auto;
      padding: 24px 18px 42px;
    }
    .title {
      display: flex;
      justify-content: space-between;
      align-items: baseline;
      gap: 12px;
      margin-bottom: 14px;
    }
    h1 {
      margin: 0;
      font-size: 1.8rem;
      letter-spacing: 0.01em;
    }
    .chip {
      font-family: "IBM Plex Mono", monospace;
      font-size: 0.8rem;
      background: #e8f5e9;
      border: 1px solid #cce3d4;
      border-radius: 999px;
      padding: 5px 10px;
    }
    .grid {
      display: grid;
      grid-template-columns: 1fr 1fr;
      gap: 14px;
    }
    .panel {
      background: var(--card);
      border: 1px solid #d9e2d4;
      border-radius: var(--radius);
      padding: 14px;
      box-shadow: 0 10px 20px rgba(19, 42, 19, 0.05);
    }
    .panel h2 {
      margin: 0 0 10px;
      font-size: 1.05rem;
    }
    .row { margin: 10px 0; }
    label {
      display: block;
      font-size: 0.86rem;
      color: var(--muted);
      margin-bottom: 6px;
    }
    select, textarea, button, input {
      width: 100%;
      border-radius: 10px;
      border: 1px solid #c5d5c7;
      padding: 9px 10px;
      font: inherit;
      color: var(--ink);
      background: #fff;
    }
    textarea {
      min-height: 150px;
      resize: vertical;
      font-family: "IBM Plex Mono", monospace;
      font-size: 0.86rem;
    }
    button {
      cursor: pointer;
      border: none;
      background: linear-gradient(135deg, var(--accent), #1b4332);
      color: #fff;
      font-weight: 700;
      transition: transform 120ms ease;
    }
    button:hover { transform: translateY(-1px); }
    button.secondary { background: linear-gradient(135deg, #52796f, #354f52); }
    button:disabled { background: #8ca798; cursor: not-allowed; }
    .status {
      padding: 8px 10px;
      border-radius: 10px;
      font-family: "IBM Plex Mono", monospace;
      font-size: 0.84rem;
      background: #f0f7f1;
      border: 1px solid #d6e6d7;
    }
    .status.err {
      background: #fdecec;
      border-color: #f4c7c7;
      color: var(--danger);
    }
    pre {
      margin: 0;
      background: #101b10;
      color: #d8f3dc;
      border-radius: 10px;
      padding: 11px;
      overflow: auto;
      min-height: 160px;
      font-family: "IBM Plex Mono", monospace;
      font-size: 0.8rem;
    }
    .full { grid-column: 1 / -1; }
    @media (max-width: 860px) {
      .grid { grid-template-columns: 1fr; }
    }
  </style>
</head>
<body>
  <main class="wrap">
    <div class="title">
      <h1>Sentinel-ZK Live Dashboard</h1>
      <span class="chip">Prover + Verifier orchestration</span>
    </div>
    <div class="grid">
      <section class="panel">
        <h2>1) Create Proof</h2>
        <div class="row">
          <label for="circuitSelect">Circuit</label>
          <select id="circuitSelect"></select>
        </div>
        <div class="row">
          <label for="privateInput">Private Input (JSON)</label>
          <textarea id="privateInput"></textarea>
        </div>
        <div class="row">
          <button id="proveBtn">Start Proof Job</button>
        </div>
        <div id="proveStatus" class="status">Idle</div>
      </section>

      <section class="panel">
        <h2>2) Verify Proof</h2>
        <div class="row">
          <label>Current Proof ID</label>
          <input id="proofId" readonly />
        </div>
        <div class="row">
          <button id="verifyBtn" class="secondary" disabled>Verify Last Completed Proof</button>
        </div>
        <div id="verifyStatus" class="status">Idle</div>
      </section>

      <section class="panel full">
        <h2>Proof/Verification Data</h2>
        <pre id="payloadView">No data yet.</pre>
      </section>
    </div>
  </main>

  <script>
    const circuitSelect = document.getElementById("circuitSelect");
    const privateInput = document.getElementById("privateInput");
    const proveBtn = document.getElementById("proveBtn");
    const proveStatus = document.getElementById("proveStatus");
    const verifyBtn = document.getElementById("verifyBtn");
    const verifyStatus = document.getElementById("verifyStatus");
    const payloadView = document.getElementById("payloadView");
    const proofIdInput = document.getElementById("proofId");

    let manifests = [];
    let currentProofId = "";
    let latestCompleted = null;
    let pollTimer = null;

    function setStatus(el, text, isError = false) {
      el.textContent = text;
      el.classList.toggle("err", isError);
    }

    function pretty(data) {
      return JSON.stringify(data, null, 2);
    }

    function defaultInputFromManifest(manifest) {
      const props = manifest?.input_schema?.properties || {};
      const required = manifest?.input_schema?.required || [];
      const data = {};
      for (const key of required) {
        const type = props[key]?.type;
        if (type === "integer" || type === "number") data[key] = 0;
        else if (type === "boolean") data[key] = false;
        else if (type === "array") data[key] = [];
        else if (type === "object") data[key] = {};
        else data[key] = "";
      }
      return data;
    }

    async function loadCircuits() {
      const res = await fetch("/api/circuits");
      const data = await res.json();
      manifests = data.circuits || [];
      circuitSelect.innerHTML = manifests
        .map((m) => `<option value="${m.circuit_id}">${m.circuit_id} (v${m.version})</option>`)
        .join("");

      if (manifests.length > 0) {
        privateInput.value = pretty(defaultInputFromManifest(manifests[0]));
      } else {
        privateInput.value = "{}";
      }
    }

    circuitSelect.addEventListener("change", () => {
      const m = manifests.find((x) => x.circuit_id === circuitSelect.value);
      privateInput.value = pretty(defaultInputFromManifest(m));
    });

    async function pollStatus(proofId) {
      if (pollTimer) clearInterval(pollTimer);
      pollTimer = setInterval(async () => {
        const res = await fetch(`/api/demo/proofs/${proofId}`);
        const body = await res.json();
        if (!res.ok) {
          setStatus(proveStatus, `Polling failed: ${body?.error?.message || res.statusText}`, true);
          clearInterval(pollTimer);
          return;
        }

        setStatus(proveStatus, `Proof ${proofId}: ${body.status}`);
        payloadView.textContent = pretty(body);
        if (body.status === "completed") {
          latestCompleted = body;
          verifyBtn.disabled = false;
          clearInterval(pollTimer);
        }
        if (body.status === "failed") {
          verifyBtn.disabled = true;
          clearInterval(pollTimer);
        }
      }, 2000);
    }

    proveBtn.addEventListener("click", async () => {
      verifyBtn.disabled = true;
      latestCompleted = null;
      let parsed;
      try {
        parsed = JSON.parse(privateInput.value);
      } catch (err) {
        setStatus(proveStatus, `Invalid JSON: ${err.message}`, true);
        return;
      }

      setStatus(proveStatus, "Submitting proof job...");
      const res = await fetch("/api/demo/prove", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({
          circuit_id: circuitSelect.value,
          private_input: parsed
        })
      });
      const body = await res.json();
      if (!res.ok) {
        setStatus(proveStatus, `Submit failed: ${body?.error?.message || res.statusText}`, true);
        payloadView.textContent = pretty(body);
        return;
      }

      currentProofId = body.proof_id;
      proofIdInput.value = currentProofId;
      setStatus(proveStatus, `Proof ${currentProofId}: queued`);
      payloadView.textContent = pretty(body);
      pollStatus(currentProofId);
    });

    verifyBtn.addEventListener("click", async () => {
      if (!latestCompleted?.proof) {
        setStatus(verifyStatus, "No completed proof available", true);
        return;
      }

      setStatus(verifyStatus, "Verifying proof...");
      const res = await fetch("/api/demo/verify", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({
          circuit_id: latestCompleted.circuit_id,
          proof: latestCompleted.proof,
          public_signals: latestCompleted.public_signals
        })
      });
      const body = await res.json();
      if (!res.ok) {
        setStatus(verifyStatus, `Verify failed: ${body?.error?.message || res.statusText}`, true);
        payloadView.textContent = pretty(body);
        return;
      }
      setStatus(verifyStatus, `Verification result: ${body.valid ? "VALID" : "INVALID"}`);
      payloadView.textContent = pretty(body);
    });

    loadCircuits().catch((err) => {
      setStatus(proveStatus, `Circuit load failed: ${err.message}`, true);
    });
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
async def demo_prove(payload: DemoProveRequest) -> dict[str, Any]:
    body = payload.model_dump_json().encode("utf-8")
    token = _jwt_token()
    path = "/v1/proofs"
    headers = {
        "Authorization": f"Bearer {token}",
        "Content-Type": "application/json",
        **_handshake_headers("POST", path, body),
    }
    async with httpx.AsyncClient(timeout=60.0) as client:
        response = await client.post(f"{config.prover_url}{path}", content=body, headers=headers)
    if response.status_code != 202:
        raise _upstream_error("prover", response)
    return response.json()


@app.get("/api/demo/proofs/{proof_id}")
async def demo_proof_status(proof_id: str) -> dict[str, Any]:
    token = _jwt_token()
    path = f"/v1/proofs/{proof_id}"
    headers = {"Authorization": f"Bearer {token}"}
    async with httpx.AsyncClient(timeout=30.0) as client:
        response = await client.get(f"{config.prover_url}{path}", headers=headers)
    if response.status_code != 200:
        raise _upstream_error("prover", response)
    return response.json()


@app.post("/api/demo/verify")
async def demo_verify(payload: DemoVerifyRequest) -> dict[str, Any]:
    token = _jwt_token()
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


if __name__ == "__main__":
    import uvicorn

    uvicorn.run("dashboard_service:app", host="0.0.0.0", port=8000, reload=False)
