"""Tests for Database layer."""

from __future__ import annotations

import asyncio
from datetime import datetime, timezone
from typing import Any

import pytest

from vellum_core.database import (
    AuditAppendInput,
    AuditLog,
    Database,
    ProofJob,
    SecurityEvent,
    _normalize_audit_payload,
    _utc_now,
)


class _FakeScalars:
    def __init__(self, values: list[Any]) -> None:
        self._values = values

    def all(self) -> list[Any]:
        return self._values


class _FakeResult:
    def __init__(
        self,
        *,
        scalars_all: list[Any] | None = None,
        scalar_one_or_none_value: Any = None,
        scalar_one_value: Any = None,
    ) -> None:
        self._scalars_all = scalars_all or []
        self._scalar_one_or_none_value = scalar_one_or_none_value
        self._scalar_one_value = scalar_one_value

    def scalars(self) -> _FakeScalars:
        return _FakeScalars(self._scalars_all)

    def scalar_one_or_none(self) -> Any:
        return self._scalar_one_or_none_value

    def scalar_one(self) -> Any:
        return self._scalar_one_value


class _FakeSession:
    def __init__(self) -> None:
        self.get_map: dict[tuple[Any, str], Any] = {}
        self.execute_queue: list[_FakeResult] = []
        self.added: list[Any] = []
        self.refresh_calls: list[Any] = []
        self.execute_calls: list[tuple[Any, dict[str, Any] | None]] = []
        self.commits = 0

    async def get(self, model: Any, key: str) -> Any:
        return self.get_map.get((model, key))

    def add(self, obj: Any) -> None:
        self.added.append(obj)

    async def commit(self) -> None:
        self.commits += 1

    async def refresh(self, obj: Any) -> None:
        self.refresh_calls.append(obj)

    async def execute(self, query: Any, params: dict[str, Any] | None = None) -> _FakeResult:
        self.execute_calls.append((query, params))
        if self.execute_queue:
            return self.execute_queue.pop(0)
        return _FakeResult()


class _FakeSessionContext:
    def __init__(self, session: _FakeSession) -> None:
        self.session = session

    async def __aenter__(self) -> _FakeSession:
        return self.session

    async def __aexit__(self, exc_type, exc, tb) -> None:  # type: ignore[no-untyped-def]
        _ = (exc_type, exc, tb)


def _db_with_session(session: _FakeSession) -> Database:
    db = object.__new__(Database)
    db.session_factory = lambda: _FakeSessionContext(session)  # type: ignore[assignment]
    return db


def test_utc_now_is_timezone_aware() -> None:
    now = _utc_now()
    assert now.tzinfo is not None
    assert now.tzinfo == timezone.utc


def test_normalize_audit_payload_from_dict_and_dataclass() -> None:
    payload = {
        "timestamp": datetime.now(timezone.utc),
        "circuit_id": "c1",
        "status": "completed",
        "entry_hash": "h",
        "signature": "s",
    }
    normalized = _normalize_audit_payload(payload)
    assert isinstance(normalized, AuditAppendInput)
    assert normalized.proof_id is None
    assert normalized.public_signals == []
    assert normalized.key_version == "0"

    same = _normalize_audit_payload(normalized)
    assert same is normalized


def test_create_and_get_proof_job() -> None:
    session = _FakeSession()
    db = _db_with_session(session)
    created = asyncio.run(
        db.create_proof_job(
            proof_id="p1",
            circuit_id="batch_credit_check",
            status="queued",
            sealed_job_payload="cipher",
            input_fingerprint="fp",
            input_summary={"mode": "private_input"},
            metadata={"bank_key_id": "k1"},
        )
    )
    assert isinstance(created, ProofJob)
    assert created.proof_id == "p1"
    assert created.meta["bank_key_id"] == "k1"
    assert session.commits == 1
    assert session.refresh_calls and session.refresh_calls[0] is created

    session.get_map[(ProofJob, "p1")] = created
    fetched = asyncio.run(db.get_proof_job("p1"))
    assert fetched is created


def test_list_proof_jobs_with_filters() -> None:
    session = _FakeSession()
    db = _db_with_session(session)
    jobs = [ProofJob(proof_id="a", circuit_id="c", status="queued")]
    session.execute_queue.append(_FakeResult(scalars_all=jobs))
    rows = asyncio.run(db.list_proof_jobs(status="queued", circuit_id="c", limit=500))
    assert rows == jobs
    assert len(session.execute_calls) == 1


def test_update_proof_job_none_and_success() -> None:
    session = _FakeSession()
    db = _db_with_session(session)

    none_case = asyncio.run(db.update_proof_job(proof_id="missing", status="failed"))
    assert none_case is None

    job = ProofJob(proof_id="p2", circuit_id="c", status="queued")
    session.get_map[(ProofJob, "p2")] = job
    updated = asyncio.run(
        db.update_proof_job(
            proof_id="p2",
            status="completed",
            public_signals=["1"],
            proof={"pi_a": ["1"]},
            proof_path="/tmp/p2.json",
            error="none",
        )
    )
    assert updated is job
    assert job.status == "completed"
    assert job.public_signals == ["1"]
    assert job.proof == {"pi_a": ["1"]}
    assert job.proof_path == "/tmp/p2.json"
    assert job.error == "none"
    assert job.updated_at is not None


def test_purge_sealed_job_payload_none_and_success() -> None:
    session = _FakeSession()
    db = _db_with_session(session)

    missing = asyncio.run(db.purge_sealed_job_payload(proof_id="x"))
    assert missing is None

    job = ProofJob(proof_id="p3", circuit_id="c", status="completed", sealed_job_payload="cipher")
    session.get_map[(ProofJob, "p3")] = job
    purged = asyncio.run(db.purge_sealed_job_payload(proof_id="p3"))
    assert purged is job
    assert job.sealed_job_payload is None
    assert job.sealed_purged_at is not None
    assert job.updated_at == job.sealed_purged_at


def test_append_audit_row_conflict_and_success() -> None:
    session = _FakeSession()
    db = _db_with_session(session)
    payload = AuditAppendInput(
        timestamp=datetime.now(timezone.utc),
        proof_id="p4",
        circuit_id="c",
        status="completed",
        public_signals=[],
        proof_hash="ph",
        previous_entry_hash="unexpected",
        entry_hash="eh",
        signature="sig",
        key_version="1",
        meta={},
        error=None,
    )
    latest = AuditLog(entry_hash="prev")
    session.execute_queue = [
        _FakeResult(),  # advisory lock
        _FakeResult(scalar_one_or_none_value=latest),
    ]
    with pytest.raises(RuntimeError, match="audit_chain_conflict"):
        asyncio.run(db.append_audit_row(payload))

    session2 = _FakeSession()
    db2 = _db_with_session(session2)
    payload_ok = AuditAppendInput(
        timestamp=datetime.now(timezone.utc),
        proof_id="p5",
        circuit_id="c",
        status="completed",
        public_signals=["1"],
        proof_hash="ph",
        previous_entry_hash="",
        entry_hash="eh2",
        signature="sig2",
        key_version="2",
        meta={"k": "v"},
        error=None,
    )
    session2.execute_queue = [
        _FakeResult(),  # advisory lock
        _FakeResult(scalar_one_or_none_value=None),
    ]
    row = asyncio.run(db2.append_audit_row(payload_ok))
    assert isinstance(row, AuditLog)
    assert row.entry_hash == "eh2"
    assert session2.commits == 1


def test_audit_read_helpers_and_count() -> None:
    session = _FakeSession()
    db = _db_with_session(session)

    latest = AuditLog(entry_hash="latest")
    session.execute_queue.append(_FakeResult(scalar_one_or_none_value=latest))
    got_latest = asyncio.run(db.get_latest_audit_row())
    assert got_latest is latest

    rows = [AuditLog(entry_hash="a"), AuditLog(entry_hash="b")]
    session.execute_queue.append(_FakeResult(scalars_all=rows))
    got_rows = asyncio.run(db.list_audit_rows())
    assert got_rows == rows

    session.execute_queue.append(_FakeResult(scalar_one_value=7))
    count = asyncio.run(db.count_jobs_by_status("completed"))
    assert count == 7


def test_append_security_event_defaults_and_fields() -> None:
    session = _FakeSession()
    db = _db_with_session(session)
    row = asyncio.run(
        db.append_security_event(
            event_type="jwt_invalid",
            outcome="denied",
            actor="alice",
            source_ip="10.0.0.1",
            proof_id="p6",
            details=None,
        )
    )
    assert isinstance(row, SecurityEvent)
    assert row.event_type == "jwt_invalid"
    assert row.outcome == "denied"
    assert row.details == {}
