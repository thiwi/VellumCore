"""Reference dashboard service exposing operations cockpit and proxy APIs."""

from __future__ import annotations

import asyncio
import json
import logging
import os
import socket
import time
from pathlib import Path
from typing import Any
from uuid import uuid4

import httpx
from fastapi import Depends, FastAPI, Query, Request
from fastapi.responses import HTMLResponse
from pydantic import BaseModel, ConfigDict, Field, ValidationError, model_validator

from vellum_core.auth import AuthManager, VaultJWTSigner, build_canonical_request_string
from vellum_core.errors import APIError, register_exception_handlers
from vellum_core.http_auth import build_optional_scoped_jwt_dependency
from vellum_core.logic.batcher import MAX_BATCH_SIZE
from vellum_core.observability import configure_logging, init_telemetry
from vellum_core.vault import VaultPublicKeyCache, VaultTransitClient
from vellum_core.versioning import HTTP_API_PREFIX, PACKAGE_VERSION


class DemoBatchProveRequest(BaseModel):
    """Request model forwarded to prover demo submit endpoint."""

    model_config = ConfigDict(extra="forbid")

    circuit_id: str | None = None
    balances: list[int] | None = Field(
        default=None,
        min_length=1,
        max_length=MAX_BATCH_SIZE,
    )
    limits: list[int] | None = Field(
        default=None,
        min_length=1,
        max_length=MAX_BATCH_SIZE,
    )
    private_input: dict[str, Any] | None = None

    @model_validator(mode="after")
    def validate_input_mode(self) -> "DemoBatchProveRequest":
        using_balances_limits = self.balances is not None or self.limits is not None
        using_private_input = self.private_input is not None
        modes = int(using_balances_limits) + int(using_private_input)
        if modes != 1:
            raise ValueError(
                "Provide exactly one input mode: balances/limits or private_input"
            )
        if using_balances_limits:
            if self.balances is None or self.limits is None:
                raise ValueError("balances and limits must both be provided for direct mode")
            if len(self.balances) != len(self.limits):
                raise ValueError("balances and limits length mismatch")
        return self


class DemoVerifyRequest(BaseModel):
    """Request model forwarded to verifier demo endpoint."""

    circuit_id: str
    proof: dict[str, Any]
    public_signals: list[Any]


class DemoPolicyRunRequest(BaseModel):
    """Request model for v6 run demo flow."""

    policy_id: str = "lending_risk_v1"
    evidence_payload: dict[str, Any] | None = None
    evidence_ref: str | None = None
    context: dict[str, Any] | None = None
    client_request_id: str | None = None

    @model_validator(mode="after")
    def validate_evidence(self) -> "DemoPolicyRunRequest":
        if self.evidence_payload is None and self.evidence_ref is None:
            raise ValueError("Provide evidence_payload or evidence_ref")
        if self.evidence_payload is not None and self.evidence_ref is not None:
            raise ValueError("Provide only one evidence source")
        return self

    def to_v6_payload(self) -> dict[str, Any]:
        evidence: dict[str, Any]
        if self.evidence_payload is not None:
            evidence = {"type": "inline", "payload": self.evidence_payload}
        else:
            assert self.evidence_ref is not None
            evidence = {"type": "ref", "ref": self.evidence_ref}
        return {
            "policy_id": self.policy_id,
            "evidence": evidence,
            "context": self.context or {},
            "client_request_id": self.client_request_id,
        }


class DashboardConfig:
    """Environment-backed configuration for dashboard upstream integrations."""

    def __init__(self) -> None:
        self.app_name = os.getenv("APP_NAME", "vellum-dashboard")
        self.prover_url = os.getenv("PROVER_URL", "http://prover:8001")
        self.verifier_url = os.getenv("VERIFIER_URL", "http://verifier:8002")
        self.worker_metrics_url = os.getenv("WORKER_METRICS_URL", "http://worker:9108/metrics")
        self.jwt_issuer = os.getenv("JWT_ISSUER", "bank.local")
        self.jwt_audience = os.getenv("JWT_AUDIENCE", "sentinel-zk")
        self.bank_key_id = os.getenv("BANK_KEY_ID", "bank-key-1")
        self.circuits_dir = Path(os.getenv("CIRCUITS_DIR", "/app/circuits"))

        self.vault_addr = os.getenv("VAULT_ADDR", "http://vault:8200")
        self.vault_token = os.getenv("VAULT_TOKEN", "root")
        self.vault_jwt_key = os.getenv("VELLUM_JWT_KEY", "vellum-jwt")
        self.vault_bank_key = os.getenv("VELLUM_BANK_KEY", "vellum-bank")
        self.vault_public_key_cache_ttl_seconds = int(
            os.getenv("VAULT_PUBLIC_KEY_CACHE_TTL_SECONDS", "300")
        )
        self.tls_ca_bundle = os.getenv("TLS_CA_BUNDLE")
        self.redis_url = os.getenv("REDIS_URL", "redis://redis:6379/1")
        self.nonce_window_seconds = int(os.getenv("NONCE_WINDOW_SECONDS", "300"))
        self.jwt_max_ttl_seconds = max(1, int(os.getenv("JWT_MAX_TTL_SECONDS", "900")))
        self.jwt_leeway_seconds = max(0, int(os.getenv("JWT_LEEWAY_SECONDS", "30")))
        self.submit_rate_limit_per_minute = max(
            0, int(os.getenv("SUBMIT_RATE_LIMIT_PER_MINUTE", "30"))
        )

        self.redis_host = os.getenv("REDIS_HOST", "redis")
        self.redis_port = int(os.getenv("REDIS_PORT", "6379"))
        self.postgres_host = os.getenv("POSTGRES_HOST", "postgres")
        self.postgres_port = int(os.getenv("POSTGRES_PORT", "5432"))
        self.dashboard_require_auth = _parse_bool_env("DASHBOARD_REQUIRE_AUTH", default=True)
        self.dashboard_auth_read_scope = os.getenv(
            "DASHBOARD_AUTH_READ_SCOPE", "dashboard:read"
        )
        self.dashboard_auth_write_scope = os.getenv(
            "DASHBOARD_AUTH_WRITE_SCOPE", "dashboard:write"
        )
        self.dashboard_max_demo_prove_body_bytes = max(
            1,
            int(os.getenv("DASHBOARD_MAX_DEMO_PROVE_BODY_BYTES", "1048576")),
        )


def _parse_bool_env(name: str, *, default: bool) -> bool:
    raw = os.getenv(name)
    if raw is None:
        return default
    value = raw.strip().lower()
    if value in {"1", "true", "yes", "on"}:
        return True
    if value in {"0", "false", "no", "off"}:
        return False
    raise ValueError(f"{name} must be a boolean value")


config = DashboardConfig()
configure_logging(config.app_name)
logger = logging.getLogger(__name__)
vault_client = VaultTransitClient(
    addr=config.vault_addr,
    token=config.vault_token,
    tls_ca_bundle=config.tls_ca_bundle,
)
jwt_signer = VaultJWTSigner(
    vault_client=vault_client,
    key_name=config.vault_jwt_key,
    issuer=config.jwt_issuer,
    audience=config.jwt_audience,
)
key_cache = VaultPublicKeyCache(
    client=vault_client,
    ttl_seconds=config.vault_public_key_cache_ttl_seconds,
)
dashboard_auth_manager = AuthManager(
    vault_client=vault_client,
    key_cache=key_cache,
    jwt_key_name=config.vault_jwt_key,
    jwt_issuer=config.jwt_issuer,
    jwt_audience=config.jwt_audience,
    bank_key_mapping={config.bank_key_id: config.vault_bank_key},
    redis_url=config.redis_url,
    nonce_window_seconds=config.nonce_window_seconds,
    jwt_max_ttl_seconds=config.jwt_max_ttl_seconds,
    jwt_leeway_seconds=config.jwt_leeway_seconds,
    submit_rate_limit_per_minute=config.submit_rate_limit_per_minute,
    security_event_recorder=None,
)

app = FastAPI(title="Vellum Framework Console", version=PACKAGE_VERSION)
register_exception_handlers(app)
init_telemetry(
    service_name=config.app_name,
    fastapi_app=app,
    instrument_httpx=True,
)

_shared_http_client: httpx.AsyncClient | None = None


class _DashboardJWTCache:
    """Cache dashboard upstream JWTs to avoid Vault signing per request."""

    def __init__(
        self,
        *,
        signer: VaultJWTSigner,
        subject: str,
        scopes: set[str],
        ttl_seconds: int,
        refresh_skew_seconds: int = 60,
    ) -> None:
        self.signer = signer
        self.subject = subject
        self.scopes = scopes
        self.ttl_seconds = ttl_seconds
        self.refresh_skew_seconds = refresh_skew_seconds
        self._token: str | None = None
        self._expires_at_epoch = 0.0
        self._lock = asyncio.Lock()

    async def get_token(self) -> str:
        now = time.time()
        if self._token is not None and now < (self._expires_at_epoch - self.refresh_skew_seconds):
            return self._token

        async with self._lock:
            now = time.time()
            if self._token is not None and now < (self._expires_at_epoch - self.refresh_skew_seconds):
                return self._token
            token = await self.signer.sign(
                subject=self.subject,
                ttl_seconds=self.ttl_seconds,
                scopes=self.scopes,
            )
            self._token = token
            self._expires_at_epoch = now + self.ttl_seconds
            return token


_UPSTREAM_JWT_TTL_SECONDS = 600
_upstream_jwt_cache = _DashboardJWTCache(
    signer=jwt_signer,
    subject="dashboard-demo-user",
    scopes={"proofs:write", "proofs:read", "audit:read", "ops:read", "ops:write"},
    ttl_seconds=_UPSTREAM_JWT_TTL_SECONDS,
    refresh_skew_seconds=60,
)


async def _jwt_token() -> str:
    """Mint dashboard-internal bearer token for upstream service calls."""
    return await _upstream_jwt_cache.get_token()


async def _get_shared_http_client() -> httpx.AsyncClient:
    """Return singleton async HTTP client for dashboard upstream traffic."""
    global _shared_http_client
    client = _shared_http_client
    if client is None or client.is_closed:
        client = httpx.AsyncClient()
        _shared_http_client = client
    return client


async def _close_shared_http_client() -> None:
    """Close singleton dashboard HTTP client if initialized."""
    global _shared_http_client
    client = _shared_http_client
    _shared_http_client = None
    if client is not None and not client.is_closed:
        await client.aclose()


def _dashboard_auth_enabled() -> bool:
    return config.dashboard_require_auth


def require_dashboard_read_scope():
    """Build optional dashboard route guard for read-only API routes."""
    return build_optional_scoped_jwt_dependency(
        dashboard_auth_manager,
        config.dashboard_auth_read_scope,
        enabled=_dashboard_auth_enabled,
    )


def require_dashboard_write_scope():
    """Build optional dashboard route guard for mutating API routes."""
    return build_optional_scoped_jwt_dependency(
        dashboard_auth_manager,
        config.dashboard_auth_write_scope,
        enabled=_dashboard_auth_enabled,
    )


async def _upstream_bearer_headers() -> dict[str, str]:
    token = await _jwt_token()
    return {"Authorization": f"Bearer {token}"}


@app.on_event("startup")
async def startup_event() -> None:
    """Initialize shared dashboard clients."""
    await _get_shared_http_client()


@app.on_event("shutdown")
async def shutdown_event() -> None:
    """Release dashboard network clients."""
    await _close_shared_http_client()
    await vault_client.aclose()


async def _handshake_headers(method: str, path: str, body: bytes) -> dict[str, str]:
    """Build bank-signature headers used for prover submit calls."""
    ts = str(int(time.time()))
    nonce = str(uuid4())
    canonical = build_canonical_request_string(
        method=method,
        path=path,
        timestamp=ts,
        nonce=nonce,
        raw_body=body,
    ).encode("utf-8")
    signature = await vault_client.sign(config.vault_bank_key, canonical)
    return {
        "X-Bank-Key-Id": config.bank_key_id,
        "X-Bank-Timestamp": ts,
        "X-Bank-Nonce": nonce,
        "X-Bank-Signature": signature.encoded,
    }


def _load_circuits() -> list[dict[str, Any]]:
    """Load circuit manifests directly from configured circuits directory."""
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
    """Normalize upstream HTTP failure into structured APIError."""
    details: dict[str, Any] = {"service": service, "status_code": response.status_code}
    try:
        details["response"] = response.json()
    except Exception:
        details["response"] = response.text
    logger.warning(
        "upstream_error",
        extra={"service": service, "status_code": response.status_code},
    )
    return APIError(
        status_code=response.status_code,
        code="upstream_error",
        message=f"{service} request failed",
        details=details,
    )


async def _proxy_get_json(
    *,
    service: str,
    url: str,
    headers: dict[str, str],
    timeout: float = 30.0,
    params: dict[str, str] | None = None,
) -> dict[str, Any]:
    """Issue one upstream GET and return parsed JSON with normalized error handling."""
    client = await _get_shared_http_client()
    response = await client.get(url, headers=headers, params=params, timeout=timeout)
    if response.status_code != 200:
        raise _upstream_error(service, response)
    return response.json()


async def _proxy_post_json(
    *,
    service: str,
    url: str,
    headers: dict[str, str],
    content: bytes,
    timeout: float = 60.0,
    expected_status: int = 200,
) -> dict[str, Any]:
    """Issue one upstream JSON POST and return parsed JSON with normalized error handling."""
    client = await _get_shared_http_client()
    response = await client.post(url, headers=headers, content=content, timeout=timeout)
    if response.status_code != expected_status:
        raise _upstream_error(service, response)
    return response.json()


async def _http_status(name: str, url: str, *, headers: dict[str, str] | None = None) -> dict[str, Any]:
    """Collect one HTTP-based component health check result."""
    try:
        client = await _get_shared_http_client()
        response = await client.get(url, headers=headers, timeout=5.0)
        return {
            "component": name,
            "ok": response.status_code < 400,
            "status_code": response.status_code,
            "detail": "ok" if response.status_code < 400 else response.text,
        }
    except Exception as exc:
        return {
            "component": name,
            "ok": False,
            "status_code": None,
            "detail": str(exc),
        }


async def _tcp_status(name: str, host: str, port: int) -> dict[str, Any]:
    """Collect one TCP reachability component health check result."""
    def _probe() -> dict[str, Any]:
        sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        sock.settimeout(2.0)
        try:
            sock.connect((host, port))
            return {"component": name, "ok": True, "status_code": None, "detail": "ok"}
        except Exception as exc:
            return {"component": name, "ok": False, "status_code": None, "detail": str(exc)}
        finally:
            sock.close()

    return await asyncio.to_thread(_probe)


async def _framework_health_snapshot() -> dict[str, Any]:
    """Aggregate health state for core framework dependencies."""
    auth_headers = await _upstream_bearer_headers()
    vault_headers = {"X-Vault-Token": config.vault_token}

    checks = await asyncio.gather(
        _http_status("prover", f"{config.prover_url}/healthz"),
        _http_status("verifier", f"{config.verifier_url}/healthz"),
        _http_status("worker", config.worker_metrics_url),
        _http_status("vault", f"{config.vault_addr}/v1/sys/health", headers=vault_headers),
        _tcp_status("redis", config.redis_host, config.redis_port),
        _tcp_status("postgres", config.postgres_host, config.postgres_port),
        _http_status(
            "trust_speed",
            f"{config.verifier_url}{HTTP_API_PREFIX}/trust-speed",
            headers=auth_headers,
        ),
    )

    components = {
        item["component"]: {
            "status": "ok" if item["ok"] else "down",
            "status_code": item["status_code"],
            "detail": item["detail"],
        }
        for item in checks
    }
    status = "ok" if all(item["ok"] for item in checks) else "degraded"
    logger.info(
        "framework_health_snapshot",
        extra={"status": status},
    )
    return {"status": status, "components": components}


async def _list_proofs(
    *,
    status: str | None = None,
    circuit_id: str | None = None,
    limit: int = 50,
) -> dict[str, Any]:
    """Fetch job list from prover service with optional filters."""
    params = {
        "limit": str(min(max(limit, 1), 200)),
    }
    if status is not None:
        params["status"] = status
    if circuit_id is not None:
        params["circuit_id"] = circuit_id

    return await _proxy_get_json(
        service="prover",
        url=f"{config.prover_url}{HTTP_API_PREFIX}/proofs",
        headers=await _upstream_bearer_headers(),
        params=params,
    )


def _iso_now() -> str:
    """Return UTC timestamp string for API payloads."""
    return time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime())


@app.get("/", response_class=HTMLResponse)
async def dashboard() -> HTMLResponse:
    """Serve operations cockpit single-page HTML application."""
    return HTMLResponse(
        """
<!doctype html>
<html lang="en">
<head>
  <meta charset="utf-8" />
  <meta name="viewport" content="width=device-width, initial-scale=1" />
  <title>Vellum Core Operations</title>
  <style>
    :root {
      --bg: #edf2f7;
      --fg: #1b2430;
      --muted: #556173;
      --card: #ffffff;
      --line: #d7dee8;
      --accent: #0f766e;
      --accent-strong: #0b5e58;
      --secondary: #215089;
      --ok: #1f9d55;
      --warn: #b7791f;
      --bad: #c53030;
      --running: #2b6cb0;
      --queued: #7b5ea7;
      --surface: #f8fbff;
    }
    * { box-sizing: border-box; }
    body {
      margin: 0;
      font-family: "Avenir Next", "Segoe UI", sans-serif;
      background: radial-gradient(1400px 700px at 100% -20%, #dbeafe, transparent 60%), var(--bg);
      color: var(--fg);
    }
    main { max-width: 1280px; margin: 0 auto; padding: 16px; }
    h1 { margin: 0; font-size: 28px; letter-spacing: .2px; }
    h2 { margin: 0; font-size: 18px; }
    h3 { margin: 0 0 10px 0; font-size: 15px; }
    .muted { color: var(--muted); }
    .layout { display: grid; gap: 12px; }
    .card {
      background: var(--card);
      border: 1px solid var(--line);
      border-radius: 14px;
      padding: 12px;
      box-shadow: 0 4px 12px rgba(27, 36, 48, 0.04);
    }
    .topbar {
      display: flex;
      gap: 12px;
      align-items: center;
      justify-content: space-between;
      margin-bottom: 12px;
    }
    .topbar-left { display: flex; flex-direction: column; gap: 4px; }
    .polling {
      font-size: 12px;
      padding: 6px 10px;
      border-radius: 999px;
      border: 1px solid var(--line);
      background: #f8fafc;
      display: inline-flex;
      align-items: center;
      gap: 8px;
    }
    .dot { width: 8px; height: 8px; border-radius: 999px; display: inline-block; background: var(--ok); }
    .dot.off { background: var(--bad); }
    .kpi-grid {
      display: grid;
      grid-template-columns: repeat(4, minmax(0, 1fr));
      gap: 12px;
    }
    .kpi-label { font-size: 12px; color: var(--muted); margin-bottom: 6px; }
    .kpi-value { font-size: 26px; font-weight: 700; line-height: 1; }
    .kpi-sub { font-size: 12px; color: var(--muted); margin-top: 6px; }
    .workflow {
      display: grid;
      grid-template-columns: 1.2fr 1fr;
      gap: 12px;
    }
    .panel-title { display: flex; align-items: center; justify-content: space-between; margin-bottom: 10px; }
    .controls-row {
      display: grid;
      grid-template-columns: repeat(3, minmax(0, 1fr));
      gap: 8px;
      margin-bottom: 10px;
    }
    label { display: block; font-size: 12px; margin-bottom: 4px; color: var(--muted); }
    select, input, textarea, button {
      width: 100%;
      border-radius: 10px;
      font: inherit;
    }
    select, input, textarea {
      border: 1px solid var(--line);
      background: #fff;
      padding: 8px 10px;
    }
    textarea { min-height: 118px; font-family: "SF Mono", Menlo, monospace; }
    button {
      border: 0;
      cursor: pointer;
      padding: 9px 12px;
      font-weight: 600;
      color: #fff;
      background: var(--accent);
    }
    button:hover { background: var(--accent-strong); }
    button.secondary { background: var(--secondary); }
    button.ghost {
      background: transparent;
      color: var(--secondary);
      border: 1px solid var(--line);
    }
    .status-pill {
      display: inline-block;
      font-size: 11px;
      font-weight: 700;
      text-transform: uppercase;
      letter-spacing: .3px;
      padding: 4px 8px;
      border-radius: 999px;
      color: #fff;
    }
    .status-ok { background: var(--ok); }
    .status-down, .status-failed, .status-error { background: var(--bad); }
    .status-running { background: var(--running); }
    .status-queued { background: var(--queued); }
    .status-completed { background: var(--ok); }
    .status-warn { background: var(--warn); }
    .jobs-table {
      width: 100%;
      border-collapse: separate;
      border-spacing: 0;
      background: var(--surface);
      border: 1px solid var(--line);
      border-radius: 12px;
      overflow: hidden;
      font-size: 13px;
    }
    .jobs-table thead th {
      text-align: left;
      padding: 8px;
      color: var(--muted);
      background: #f8fafc;
      border-bottom: 1px solid var(--line);
    }
    .jobs-table tbody td { padding: 8px; border-bottom: 1px solid #e7edf4; vertical-align: top; }
    .jobs-table tbody tr { cursor: pointer; }
    .jobs-table tbody tr:hover { background: #f1f7ff; }
    .jobs-table tbody tr.selected { background: #e4f0ff; }
    .mono { font-family: "SF Mono", Menlo, monospace; font-size: 12px; }
    .job-detail-grid { display: grid; gap: 8px; grid-template-columns: repeat(2, minmax(0, 1fr)); }
    .detail-item { background: var(--surface); border: 1px solid var(--line); border-radius: 10px; padding: 8px; }
    .detail-item .label { font-size: 11px; color: var(--muted); margin-bottom: 4px; }
    .signals {
      background: #0f172a;
      color: #d7e3ff;
      border-radius: 10px;
      padding: 8px;
      max-height: 210px;
      overflow: auto;
      font-size: 12px;
    }
    .deep-dive { display: grid; grid-template-columns: 1fr 1fr; gap: 12px; }
    .tab-row { display: flex; gap: 6px; margin-bottom: 8px; flex-wrap: wrap; }
    .tab-row button { width: auto; padding: 6px 10px; font-size: 12px; }
    pre {
      margin: 0;
      background: #0c1116;
      color: #d8e7ef;
      border-radius: 10px;
      padding: 10px;
      overflow: auto;
      min-height: 180px;
      max-height: 340px;
      font-size: 12px;
    }
    details {
      border: 1px solid var(--line);
      border-radius: 10px;
      padding: 8px;
      background: #fff;
    }
    summary { cursor: pointer; font-weight: 600; }
    .error-inline { color: var(--bad); font-size: 13px; margin-top: 8px; }
    @media (max-width: 1040px) {
      .kpi-grid { grid-template-columns: repeat(2, minmax(0, 1fr)); }
      .workflow { grid-template-columns: 1fr; }
      .deep-dive { grid-template-columns: 1fr; }
      .controls-row { grid-template-columns: 1fr; }
      .job-detail-grid { grid-template-columns: 1fr; }
    }
  </style>
</head>
<body>
  <main>
    <div class="topbar">
      <div class="topbar-left">
        <h1>Vellum Core Operations</h1>
        <div class="muted">Health, proof workflow and audit verification</div>
      </div>
      <div class="polling">
        <span id="pollDot" class="dot"></span>
        <span id="pollLabel">Auto-refresh on</span>
        <button id="togglePolling" class="ghost" style="width:auto; padding:5px 8px;">Pause</button>
        <button id="refreshNow" class="ghost" style="width:auto; padding:5px 8px;">Refresh now</button>
      </div>
    </div>

    <div class="layout">
      <section class="kpi-grid">
        <div class="card">
          <div class="kpi-label">Environment</div>
          <div id="kpiEnvironment" class="kpi-value">-</div>
          <div id="kpiEnvironmentSub" class="kpi-sub">Loading...</div>
        </div>
        <div class="card">
          <div class="kpi-label">Active Jobs</div>
          <div id="kpiActiveJobs" class="kpi-value">0</div>
          <div id="kpiJobsSub" class="kpi-sub">queued + running</div>
        </div>
        <div class="card">
          <div class="kpi-label">Trust Speedup</div>
          <div id="kpiSpeed" class="kpi-value">-</div>
          <div id="kpiSpeedSub" class="kpi-sub">native vs zk batch verify</div>
        </div>
        <div class="card">
          <div class="kpi-label">Latest Error</div>
          <div id="kpiError" class="kpi-value" style="font-size:16px;">None</div>
          <div id="kpiErrorSub" class="kpi-sub">No failed jobs in recent history</div>
        </div>
      </section>

      <section class="workflow">
        <div class="card">
          <div class="panel-title">
            <h2>Workflow</h2>
            <span id="workflowStatus" class="muted mono">idle</span>
          </div>
          <label for="circuitId">Circuit</label>
          <select id="circuitId"></select>
          <label for="batchInput" style="margin-top:8px;">Proof Input (JSON)</label>
          <textarea id="batchInput">{
  "balances": [120, 220, 330],
  "limits": [100, 200, 300]
}</textarea>
          <button id="proveBtn" style="margin-top:8px;">Start Proof Job</button>
          <div id="proveError" class="error-inline" style="display:none;"></div>

          <div style="margin-top:16px;">
            <div class="panel-title">
              <h3>Job Queue</h3>
              <button id="refreshJobs" class="ghost" style="width:auto;">Refresh</button>
            </div>
            <div class="controls-row">
              <div>
                <label for="filterStatus">Status Filter</label>
                <select id="filterStatus">
                  <option value="">all</option>
                  <option value="queued">queued</option>
                  <option value="running">running</option>
                  <option value="completed">completed</option>
                  <option value="failed">failed</option>
                </select>
              </div>
              <div>
                <label for="filterCircuit">Circuit Filter</label>
                <select id="filterCircuit">
                  <option value="">all</option>
                </select>
              </div>
              <div>
                <label for="filterWindow">Time Window</label>
                <select id="filterWindow">
                  <option value="all">all</option>
                  <option value="1h">last 1h</option>
                  <option value="6h">last 6h</option>
                  <option value="24h">last 24h</option>
                </select>
              </div>
            </div>
            <table class="jobs-table">
              <thead>
                <tr>
                  <th>Status</th>
                  <th>Circuit</th>
                  <th>Proof ID</th>
                  <th>Updated</th>
                </tr>
              </thead>
              <tbody id="jobsBody">
                <tr><td colspan="4" class="muted">Loading jobs...</td></tr>
              </tbody>
            </table>
          </div>
        </div>

        <div class="card">
          <div class="panel-title">
            <h2>Selected Job</h2>
            <span id="selectedStatus" class="status-pill status-warn">none</span>
          </div>
          <div class="job-detail-grid">
            <div class="detail-item">
              <div class="label">Proof ID</div>
              <div id="detailProofId" class="mono">-</div>
            </div>
            <div class="detail-item">
              <div class="label">Circuit</div>
              <div id="detailCircuit" class="mono">-</div>
            </div>
            <div class="detail-item">
              <div class="label">Created</div>
              <div id="detailCreated" class="mono">-</div>
            </div>
            <div class="detail-item">
              <div class="label">Updated</div>
              <div id="detailUpdated" class="mono">-</div>
            </div>
          </div>

          <div style="margin-top:10px;">
            <h3>Business Signals</h3>
            <div id="signalsView" class="signals">No job selected.</div>
          </div>

          <div style="margin-top:10px; display:grid; grid-template-columns:1fr 1fr; gap:8px;">
            <button id="verifyBtn" class="secondary" disabled>Verify Selected Proof</button>
            <button id="auditBtn" class="secondary">Verify Audit Chain</button>
          </div>
          <div id="verifyStatus" class="muted" style="margin-top:8px;">Idle</div>
          <details style="margin-top:10px;">
            <summary>Technical Detail</summary>
            <div id="detailError" class="error-inline" style="display:none;"></div>
            <pre id="selectedRaw">No data.</pre>
          </details>
        </div>
      </section>

      <section class="deep-dive">
        <div class="card">
          <div class="panel-title">
            <h2>Diagnostics</h2>
            <button id="refreshDiagnostics" class="ghost" style="width:auto;">Refresh</button>
          </div>
          <pre id="diagnostics">Loading...</pre>
        </div>

        <div class="card">
          <div class="panel-title">
            <h2>Inspect</h2>
          </div>
          <div class="tab-row">
            <button id="tabOverview" class="ghost" style="width:auto;">Overview JSON</button>
            <button id="tabJob" class="ghost" style="width:auto;">Selected Job JSON</button>
            <button id="tabCircuits" class="ghost" style="width:auto;">Circuits JSON</button>
          </div>
          <pre id="inspectRaw">No data.</pre>
        </div>
      </section>
    </div>
  </main>

  <script>
    const appState = {
      overview: null,
      diagnostics: null,
      circuits: [],
      manifestByCircuit: {},
      jobs: [],
      selectedJobSummary: null,
      selectedJobFull: null,
      filters: {
        status: '',
        circuit: '',
        window: 'all',
      },
      polling: {
        enabled: true,
        intervalMs: 3000,
        handle: null,
        lastRefresh: null,
      },
      inspectTab: 'overview',
    };

    const els = {
      pollDot: document.getElementById('pollDot'),
      pollLabel: document.getElementById('pollLabel'),
      togglePolling: document.getElementById('togglePolling'),
      refreshNow: document.getElementById('refreshNow'),
      kpiEnvironment: document.getElementById('kpiEnvironment'),
      kpiEnvironmentSub: document.getElementById('kpiEnvironmentSub'),
      kpiActiveJobs: document.getElementById('kpiActiveJobs'),
      kpiJobsSub: document.getElementById('kpiJobsSub'),
      kpiSpeed: document.getElementById('kpiSpeed'),
      kpiSpeedSub: document.getElementById('kpiSpeedSub'),
      kpiError: document.getElementById('kpiError'),
      kpiErrorSub: document.getElementById('kpiErrorSub'),
      circuitId: document.getElementById('circuitId'),
      batchInput: document.getElementById('batchInput'),
      proveBtn: document.getElementById('proveBtn'),
      proveError: document.getElementById('proveError'),
      workflowStatus: document.getElementById('workflowStatus'),
      refreshJobs: document.getElementById('refreshJobs'),
      filterStatus: document.getElementById('filterStatus'),
      filterCircuit: document.getElementById('filterCircuit'),
      filterWindow: document.getElementById('filterWindow'),
      jobsBody: document.getElementById('jobsBody'),
      selectedStatus: document.getElementById('selectedStatus'),
      detailProofId: document.getElementById('detailProofId'),
      detailCircuit: document.getElementById('detailCircuit'),
      detailCreated: document.getElementById('detailCreated'),
      detailUpdated: document.getElementById('detailUpdated'),
      signalsView: document.getElementById('signalsView'),
      verifyBtn: document.getElementById('verifyBtn'),
      auditBtn: document.getElementById('auditBtn'),
      verifyStatus: document.getElementById('verifyStatus'),
      detailError: document.getElementById('detailError'),
      selectedRaw: document.getElementById('selectedRaw'),
      refreshDiagnostics: document.getElementById('refreshDiagnostics'),
      diagnostics: document.getElementById('diagnostics'),
      tabOverview: document.getElementById('tabOverview'),
      tabJob: document.getElementById('tabJob'),
      tabCircuits: document.getElementById('tabCircuits'),
      inspectRaw: document.getElementById('inspectRaw'),
    };

    async function api(path, init = {}) {
      const res = await fetch(path, init);
      const body = await res.json();
      if (!res.ok) {
        const upstream = body?.error?.details?.response?.error?.message;
        const reason = body?.error?.details?.response?.error?.details?.reason;
        const msg = [body?.error?.message, upstream, reason]
          .filter((v) => typeof v === 'string' && v.length > 0)
          .join(': ') || res.statusText || 'Request failed';
        throw new Error(msg);
      }
      return body;
    }

    function fmtTime(iso) {
      if (!iso) return '-';
      try { return new Date(iso).toLocaleString(); } catch (_) { return iso; }
    }

    function ago(iso) {
      if (!iso) return '-';
      const sec = Math.max(0, Math.floor((Date.now() - new Date(iso).getTime()) / 1000));
      if (sec < 60) return `${sec}s ago`;
      if (sec < 3600) return `${Math.floor(sec / 60)}m ago`;
      return `${Math.floor(sec / 3600)}h ago`;
    }

    function statusClass(status) {
      const raw = String(status || '').toLowerCase();
      if (!raw) return 'status-warn';
      if (raw === 'ok') return 'status-ok';
      if (raw === 'down' || raw === 'failed' || raw === 'error') return 'status-down';
      if (raw === 'running') return 'status-running';
      if (raw === 'queued') return 'status-queued';
      if (raw === 'completed') return 'status-completed';
      return 'status-warn';
    }

    function renderOverview() {
      const overview = appState.overview;
      if (!overview) return;
      const health = overview.health || {};
      const components = health.components || {};
      const down = Object.entries(components).filter(([, v]) => v.status !== 'ok').map(([k]) => k);
      const envLabel = health.status === 'ok' ? 'OK' : 'DEGRADED';
      els.kpiEnvironment.textContent = envLabel;
      els.kpiEnvironmentSub.textContent = down.length ? `Down: ${down.join(', ')}` : 'All components healthy';

      const jobs = overview.jobs || {};
      const counts = jobs.counts || {};
      els.kpiActiveJobs.textContent = String(jobs.active || 0);
      els.kpiJobsSub.textContent = `queued ${counts.queued || 0} / running ${counts.running || 0} / failed ${counts.failed || 0}`;

      const trust = overview.trust_speed || {};
      const ratio = trust.trust_speedup;
      els.kpiSpeed.textContent = ratio == null ? 'n/a' : `${Number(ratio).toFixed(2)}x`;
      els.kpiSpeedSub.textContent = `native ${trust.native_verify_ms ?? 'n/a'} ms | zk ${trust.zk_batch_verify_ms ?? 'n/a'} ms`;

      const latestFailed = jobs.latest_failed;
      if (!latestFailed) {
        els.kpiError.textContent = 'None';
        els.kpiErrorSub.textContent = 'No failed jobs in recent history';
      } else {
        els.kpiError.textContent = String(latestFailed.error || 'Failed job');
        els.kpiErrorSub.textContent = `${latestFailed.circuit_id} · ${ago(latestFailed.updated_at)}`;
      }
    }

    function applyClientFilters(items) {
      const statusFilter = appState.filters.status;
      const circuitFilter = appState.filters.circuit;
      const windowFilter = appState.filters.window;
      const now = Date.now();
      return items.filter((item) => {
        if (statusFilter && item.status !== statusFilter) return false;
        if (circuitFilter && item.circuit_id !== circuitFilter) return false;
        if (windowFilter !== 'all') {
          const hours = windowFilter === '1h' ? 1 : (windowFilter === '6h' ? 6 : 24);
          const ts = new Date(item.created_at).getTime();
          if (now - ts > hours * 3600 * 1000) return false;
        }
        return true;
      });
    }

    function renderJobs() {
      const items = applyClientFilters(appState.jobs);
      if (items.length === 0) {
        els.jobsBody.innerHTML = '<tr><td colspan="4" class="muted">No jobs for current filter.</td></tr>';
        return;
      }
      els.jobsBody.innerHTML = items.map((job) => {
        const selected = appState.selectedJobSummary?.proof_id === job.proof_id ? 'selected' : '';
        return `
          <tr class="${selected}" data-proof-id="${job.proof_id}">
            <td><span class="status-pill ${statusClass(job.status)}">${job.status}</span></td>
            <td class="mono">${job.circuit_id}</td>
            <td class="mono">${job.proof_id}</td>
            <td class="mono">${ago(job.updated_at)}</td>
          </tr>
        `;
      }).join('');
      els.jobsBody.querySelectorAll('tr[data-proof-id]').forEach((row) => {
        row.addEventListener('click', () => selectJob(row.getAttribute('data-proof-id')));
      });
    }

    function decodeSignals(job) {
      if (!job?.public_signals) return 'No public signals yet.';
      const signals = job.public_signals;
      const manifest = appState.manifestByCircuit[job.circuit_id];
      if (job.circuit_id === 'batch_credit_check') {
        const allValid = String(signals[0] ?? '');
        const activeCount = String(signals[1] ?? '');
        const verdict = allValid === '1' ? 'PASSED' : 'FAILED';
        return [
          `all_valid: ${allValid} (${verdict})`,
          `active_count_out: ${activeCount}`,
          `active_count (tail): ${String(signals[signals.length - 1] ?? '')}`,
        ].join('\\n');
      }
      if (manifest?.public_signals && manifest.public_signals.length > 0) {
        const pairs = [];
        for (let i = 0; i < Math.min(manifest.public_signals.length, signals.length); i += 1) {
          pairs.push(`${manifest.public_signals[i]}: ${signals[i]}`);
        }
        return pairs.join('\\n');
      }
      return JSON.stringify(signals, null, 2);
    }

    function renderSelectedJob() {
      const job = appState.selectedJobFull || appState.selectedJobSummary;
      if (!job) {
        els.selectedStatus.className = 'status-pill status-warn';
        els.selectedStatus.textContent = 'none';
        els.detailProofId.textContent = '-';
        els.detailCircuit.textContent = '-';
        els.detailCreated.textContent = '-';
        els.detailUpdated.textContent = '-';
        els.signalsView.textContent = 'No job selected.';
        els.verifyBtn.disabled = true;
        els.detailError.style.display = 'none';
        els.selectedRaw.textContent = 'No data.';
        return;
      }
      els.selectedStatus.className = `status-pill ${statusClass(job.status)}`;
      els.selectedStatus.textContent = job.status || 'unknown';
      els.detailProofId.textContent = job.proof_id || '-';
      els.detailCircuit.textContent = job.circuit_id || '-';
      els.detailCreated.textContent = fmtTime(job.created_at);
      els.detailUpdated.textContent = fmtTime(job.updated_at);
      els.signalsView.textContent = decodeSignals(job);
      els.verifyBtn.disabled = !(job.proof && Array.isArray(job.public_signals));
      if (job.error) {
        els.detailError.style.display = 'block';
        els.detailError.textContent = `Error: ${job.error}`;
      } else {
        els.detailError.style.display = 'none';
      }
      els.selectedRaw.textContent = JSON.stringify(job, null, 2);
    }

    function renderInspectTab() {
      if (appState.inspectTab === 'overview') {
        els.inspectRaw.textContent = JSON.stringify(appState.overview || {}, null, 2);
        return;
      }
      if (appState.inspectTab === 'job') {
        els.inspectRaw.textContent = JSON.stringify(appState.selectedJobFull || appState.selectedJobSummary || {}, null, 2);
        return;
      }
      els.inspectRaw.textContent = JSON.stringify(appState.circuits || [], null, 2);
    }

    function renderPolling() {
      els.pollDot.className = `dot ${appState.polling.enabled ? '' : 'off'}`;
      const stamp = appState.polling.lastRefresh ? ` · last ${ago(appState.polling.lastRefresh)}` : '';
      els.pollLabel.textContent = appState.polling.enabled ? `Auto-refresh on${stamp}` : `Auto-refresh paused${stamp}`;
      els.togglePolling.textContent = appState.polling.enabled ? 'Pause' : 'Resume';
    }

    function setWorkflowStatus(text, isError = false) {
      els.workflowStatus.textContent = text;
      els.workflowStatus.style.color = isError ? 'var(--bad)' : 'var(--muted)';
    }

    async function refreshOverview() {
      appState.overview = await api('/api/framework/overview');
      renderOverview();
    }

    async function refreshDiagnostics() {
      appState.diagnostics = await api('/api/framework/diagnostics');
      els.diagnostics.textContent = JSON.stringify(appState.diagnostics, null, 2);
    }

    async function refreshCircuits() {
      const manifests = await api('/api/circuits');
      const frameworks = await api('/api/framework/circuits');
      appState.circuits = manifests.circuits || [];
      appState.manifestByCircuit = Object.fromEntries(
        appState.circuits.map((entry) => [entry.circuit_id, entry])
      );
      const ids = (frameworks.circuits || []).map((entry) => entry.circuit_id);
      const allIds = Array.from(new Set([...ids, ...appState.circuits.map((entry) => entry.circuit_id)]));

      const currentCircuit = appState.filters.circuit;
      const currentSubmit = els.circuitId.value;
      els.circuitId.innerHTML = allIds.map((id) => `<option value="${id}">${id}</option>`).join('');
      els.filterCircuit.innerHTML = '<option value="">all</option>' + allIds.map((id) => `<option value="${id}">${id}</option>`).join('');
      if (allIds.length) {
        if (allIds.includes(currentSubmit)) {
          els.circuitId.value = currentSubmit;
        } else if (allIds.includes('batch_credit_check')) {
          // Keep dashboard default aligned with built-in textarea template.
          els.circuitId.value = 'batch_credit_check';
        } else {
          els.circuitId.value = allIds[0];
        }
      }
      if (currentCircuit && allIds.includes(currentCircuit)) {
        els.filterCircuit.value = currentCircuit;
      }
      renderInspectTab();
    }

    async function refreshJobs() {
      const params = new URLSearchParams({ limit: '80' });
      if (appState.filters.status) params.set('status', appState.filters.status);
      if (appState.filters.circuit) params.set('circuit_id', appState.filters.circuit);
      const body = await api(`/api/demo/proofs?${params.toString()}`);
      appState.jobs = body.items || [];

      if (!appState.selectedJobSummary && appState.jobs.length > 0) {
        appState.selectedJobSummary = appState.jobs[0];
      } else if (appState.selectedJobSummary) {
        const match = appState.jobs.find((j) => j.proof_id === appState.selectedJobSummary.proof_id);
        if (match) appState.selectedJobSummary = match;
      }
      renderJobs();
      renderSelectedJob();
    }

    async function selectJob(proofId) {
      const job = appState.jobs.find((item) => item.proof_id === proofId);
      appState.selectedJobSummary = job || null;
      appState.selectedJobFull = null;
      renderJobs();
      renderSelectedJob();
      try {
        appState.selectedJobFull = await api(`/api/demo/proofs/${proofId}`);
        renderSelectedJob();
        renderInspectTab();
      } catch (err) {
        setWorkflowStatus(`Could not load job detail: ${err.message}`, true);
      }
    }

    async function submitJob() {
      els.proveError.style.display = 'none';
      let parsed;
      try {
        parsed = JSON.parse(els.batchInput.value);
      } catch (err) {
        els.proveError.textContent = `Invalid JSON: ${err.message}`;
        els.proveError.style.display = 'block';
        return;
      }
      setWorkflowStatus('submitting...');
      const response = await api('/api/demo/prove', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({
          ...parsed,
          circuit_id: els.circuitId.value,
        }),
      });
      setWorkflowStatus(`job queued: ${response.proof_id}`);
      await Promise.all([refreshJobs(), refreshOverview()]);
      await selectJob(response.proof_id);
    }

    async function verifySelectedJob() {
      const job = appState.selectedJobFull;
      if (!job?.proof || !Array.isArray(job.public_signals)) {
        els.verifyStatus.textContent = 'No completed proof available for selected job.';
        return;
      }
      const body = await api('/api/demo/verify', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({
          circuit_id: job.circuit_id,
          proof: job.proof,
          public_signals: job.public_signals,
        }),
      });
      els.verifyStatus.textContent = `Verification: ${body.valid ? 'VALID' : 'INVALID'} (${Number(body.verification_ms).toFixed(2)} ms)`;
      await refreshOverview();
    }

    async function verifyAuditChain() {
      const body = await api('/api/framework/audit-chain');
      els.verifyStatus.textContent = `Audit chain valid: ${body.valid} (checked=${body.checked_entries})`;
      appState.inspectTab = 'overview';
      renderInspectTab();
    }

    async function refreshAll() {
      try {
        await Promise.all([
          refreshOverview(),
          refreshDiagnostics(),
          refreshCircuits(),
          refreshJobs(),
        ]);
        if (appState.selectedJobSummary && !appState.selectedJobFull) {
          await selectJob(appState.selectedJobSummary.proof_id);
        }
        setWorkflowStatus('up to date');
      } catch (err) {
        setWorkflowStatus(`refresh failed: ${err.message}`, true);
      } finally {
        appState.polling.lastRefresh = new Date().toISOString();
        renderPolling();
        renderInspectTab();
      }
    }

    function startPolling() {
      if (appState.polling.handle) clearInterval(appState.polling.handle);
      appState.polling.handle = setInterval(() => {
        if (!appState.polling.enabled) return;
        refreshAll().catch(() => {});
      }, appState.polling.intervalMs);
    }

    els.proveBtn.addEventListener('click', () => {
      submitJob().catch((err) => {
        els.proveError.textContent = err.message;
        els.proveError.style.display = 'block';
        setWorkflowStatus(`submit failed: ${err.message}`, true);
      });
    });
    els.refreshJobs.addEventListener('click', () => refreshJobs().catch((err) => setWorkflowStatus(err.message, true)));
    els.refreshDiagnostics.addEventListener('click', () => refreshDiagnostics().catch((err) => setWorkflowStatus(err.message, true)));
    els.verifyBtn.addEventListener('click', () => verifySelectedJob().catch((err) => {
      els.verifyStatus.textContent = `Verify failed: ${err.message}`;
    }));
    els.auditBtn.addEventListener('click', () => verifyAuditChain().catch((err) => {
      els.verifyStatus.textContent = `Audit failed: ${err.message}`;
    }));
    els.filterStatus.addEventListener('change', () => {
      appState.filters.status = els.filterStatus.value;
      refreshJobs().catch((err) => setWorkflowStatus(err.message, true));
    });
    els.filterCircuit.addEventListener('change', () => {
      appState.filters.circuit = els.filterCircuit.value;
      refreshJobs().catch((err) => setWorkflowStatus(err.message, true));
    });
    els.filterWindow.addEventListener('change', () => {
      appState.filters.window = els.filterWindow.value;
      renderJobs();
    });
    els.tabOverview.addEventListener('click', () => { appState.inspectTab = 'overview'; renderInspectTab(); });
    els.tabJob.addEventListener('click', () => { appState.inspectTab = 'job'; renderInspectTab(); });
    els.tabCircuits.addEventListener('click', () => { appState.inspectTab = 'circuits'; renderInspectTab(); });
    els.togglePolling.addEventListener('click', () => {
      appState.polling.enabled = !appState.polling.enabled;
      renderPolling();
    });
    els.refreshNow.addEventListener('click', () => refreshAll().catch(() => {}));

    renderPolling();
    refreshAll().catch(() => {});
    startPolling();
  </script>
</body>
</html>
        """
    )


@app.get("/healthz")
async def healthz() -> dict[str, str]:
    """Liveness endpoint for dashboard service."""
    return {"status": "ok"}


@app.get("/api/circuits")
async def list_circuits(
    _: dict[str, Any] | None = Depends(require_dashboard_read_scope()),
) -> dict[str, Any]:
    """Return local manifest list from mounted circuits directory."""
    return {"circuits": _load_circuits()}


@app.get("/api/framework/health")
async def framework_health(
    _: dict[str, Any] | None = Depends(require_dashboard_read_scope()),
) -> dict[str, Any]:
    """Return aggregated dependency health snapshot."""
    return await _framework_health_snapshot()


@app.get("/api/framework/diagnostics")
async def framework_diagnostics(
    _: dict[str, Any] | None = Depends(require_dashboard_read_scope()),
) -> dict[str, Any]:
    """Return degraded component subset for troubleshooting."""
    snapshot = await _framework_health_snapshot()
    failed = {
        name: details
        for name, details in snapshot["components"].items()
        if details.get("status") != "ok"
    }
    return {
        "status": snapshot["status"],
        "failed_components": failed,
        "summary": "all_ok" if not failed else "degraded_dependencies",
    }


@app.get("/api/framework/overview")
async def framework_overview(
    _: dict[str, Any] | None = Depends(require_dashboard_read_scope()),
) -> dict[str, Any]:
    """Return cockpit header aggregate: health, trust-speed, and recent job stats."""
    health, trust, jobs_payload = await asyncio.gather(
        _framework_health_snapshot(),
        demo_trust_speed(),
        _list_proofs(limit=50),
    )

    jobs = jobs_payload.get("items", [])
    counts = {"queued": 0, "running": 0, "completed": 0, "failed": 0}
    policy_counts = {"pass": 0, "fail": 0, "pending": 0}
    latest_failed: dict[str, Any] | None = None
    for job in jobs:
        job_status = str(job.get("status", ""))
        if job_status in counts:
            counts[job_status] += 1
        if latest_failed is None and job_status == "failed":
            latest_failed = job
        metadata = job.get("metadata") or {}
        if isinstance(metadata, dict) and metadata.get("policy_id"):
            decision = metadata.get("decision")
            if decision == "pass":
                policy_counts["pass"] += 1
            elif decision == "fail":
                policy_counts["fail"] += 1
            else:
                policy_counts["pending"] += 1

    return {
        "generated_at": _iso_now(),
        "health": health,
        "trust_speed": trust,
        "jobs": {
            "counts": counts,
            "active": counts["queued"] + counts["running"],
            "recent_total": len(jobs),
            "latest_failed": latest_failed,
            "policy_decisions": policy_counts,
        },
    }


@app.get("/api/framework/circuits")
async def framework_circuits(
    _: dict[str, Any] | None = Depends(require_dashboard_read_scope()),
) -> dict[str, Any]:
    """Proxy verifier circuit status endpoint."""
    path = f"{HTTP_API_PREFIX}/circuits"
    return await _proxy_get_json(
        service="verifier",
        url=f"{config.verifier_url}{path}",
        headers=await _upstream_bearer_headers(),
    )


@app.get("/api/framework/audit-chain")
async def framework_audit_chain(
    _: dict[str, Any] | None = Depends(require_dashboard_read_scope()),
) -> dict[str, Any]:
    """Proxy verifier audit integrity endpoint."""
    path = f"{HTTP_API_PREFIX}/audit/verify-chain"
    return await _proxy_get_json(
        service="verifier",
        url=f"{config.verifier_url}{path}",
        headers=await _upstream_bearer_headers(),
    )


@app.post("/api/demo/prove")
async def demo_prove(
    request: Request,
    _: dict[str, Any] | None = Depends(require_dashboard_write_scope()),
) -> dict[str, Any]:
    """Proxy prove submission with dashboard-minted auth and handshake headers."""
    raw_body = await request.body()
    if len(raw_body) > config.dashboard_max_demo_prove_body_bytes:
        raise APIError(
            status_code=413,
            code="payload_too_large",
            message="Request payload exceeds configured size limit",
            details={
                "path": "/api/demo/prove",
                "limit_bytes": config.dashboard_max_demo_prove_body_bytes,
                "received_bytes": len(raw_body),
            },
        )

    try:
        payload = DemoBatchProveRequest.model_validate_json(raw_body)
    except ValidationError as exc:
        raise APIError(
            status_code=422,
            code="validation_error",
            message="Request validation failed",
            details={"errors": exc.errors(include_context=False, include_input=False)},
        ) from exc

    body = payload.model_dump_json(exclude_none=True).encode("utf-8")
    path = f"{HTTP_API_PREFIX}/proofs/batch"
    headers = {
        **(await _upstream_bearer_headers()),
        "Content-Type": "application/json",
        **(await _handshake_headers("POST", path, body)),
    }
    return await _proxy_post_json(
        service="prover",
        url=f"{config.prover_url}{path}",
        headers=headers,
        content=body,
        expected_status=202,
    )


@app.get("/api/demo/proofs/{proof_id}")
async def demo_proof_status(
    proof_id: str,
    _: dict[str, Any] | None = Depends(require_dashboard_read_scope()),
) -> dict[str, Any]:
    """Proxy single proof status lookup from prover service."""
    path = f"{HTTP_API_PREFIX}/proofs/{proof_id}"
    return await _proxy_get_json(
        service="prover",
        url=f"{config.prover_url}{path}",
        headers=await _upstream_bearer_headers(),
    )


@app.get("/api/demo/proofs")
async def demo_list_proofs(
    _: dict[str, Any] | None = Depends(require_dashboard_read_scope()),
    status: str | None = Query(default=None),
    circuit_id: str | None = Query(default=None),
    limit: int = Query(default=50, ge=1, le=200),
) -> dict[str, Any]:
    """Proxy proof list endpoint with optional filters."""
    return await _list_proofs(
        status=status,
        circuit_id=circuit_id,
        limit=limit,
    )


@app.post("/api/demo/verify")
async def demo_verify(
    payload: DemoVerifyRequest,
    _: dict[str, Any] | None = Depends(require_dashboard_write_scope()),
) -> dict[str, Any]:
    """Proxy verifier proof-check endpoint."""
    path = f"{HTTP_API_PREFIX}/verify"
    headers = {**(await _upstream_bearer_headers()), "Content-Type": "application/json"}
    return await _proxy_post_json(
        service="verifier",
        url=f"{config.verifier_url}{path}",
        headers=headers,
        content=payload.model_dump_json().encode("utf-8"),
    )


@app.get("/api/trust-speed")
async def demo_trust_speed(
    _: dict[str, Any] | None = Depends(require_dashboard_read_scope()),
) -> dict[str, Any]:
    """Proxy trust-speed snapshot endpoint from verifier service."""
    path = f"{HTTP_API_PREFIX}/trust-speed"
    return await _proxy_get_json(
        service="verifier",
        url=f"{config.verifier_url}{path}",
        headers=await _upstream_bearer_headers(),
    )


@app.post("/api/v6/runs")
async def demo_policy_run(
    payload: DemoPolicyRunRequest,
    _: dict[str, Any] | None = Depends(require_dashboard_write_scope()),
) -> dict[str, Any]:
    """Proxy v6 run creation endpoint."""
    body = json.dumps(payload.to_v6_payload(), separators=(",", ":")).encode("utf-8")
    path = f"{HTTP_API_PREFIX}/runs"
    headers = {
        **(await _upstream_bearer_headers()),
        "Content-Type": "application/json",
        **(await _handshake_headers("POST", path, body)),
    }
    return await _proxy_post_json(
        service="prover",
        url=f"{config.prover_url}{path}",
        headers=headers,
        content=body,
        expected_status=202,
    )


@app.get("/api/v6/runs/{run_id}")
async def demo_policy_run_status(
    run_id: str,
    _: dict[str, Any] | None = Depends(require_dashboard_read_scope()),
) -> dict[str, Any]:
    """Proxy v6 run status endpoint."""
    path = f"{HTTP_API_PREFIX}/runs/{run_id}"
    return await _proxy_get_json(
        service="prover",
        url=f"{config.prover_url}{path}",
        headers=await _upstream_bearer_headers(),
    )


@app.get("/api/v6/runs/{run_id}/attestation")
async def demo_attestation_export(
    run_id: str,
    _: dict[str, Any] | None = Depends(require_dashboard_read_scope()),
) -> dict[str, Any]:
    """Proxy v6 attestation export endpoint."""
    path = f"{HTTP_API_PREFIX}/runs/{run_id}/attestation"
    return await _proxy_get_json(
        service="verifier",
        url=f"{config.verifier_url}{path}",
        headers=await _upstream_bearer_headers(),
    )


if __name__ == "__main__":
    import uvicorn

    uvicorn.run("dashboard_service:app", host="0.0.0.0", port=8000, reload=False)
