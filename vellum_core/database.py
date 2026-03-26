"""Async SQLAlchemy persistence layer for proof jobs and audit chain rows."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Any

from sqlalchemy import (
    JSON,
    BigInteger,
    Column,
    DateTime,
    Index,
    String,
    Text,
    desc,
    func,
    select,
    text,
)
from sqlalchemy.ext.asyncio import AsyncEngine, AsyncSession, create_async_engine
from sqlalchemy.orm import declarative_base
from sqlalchemy.orm import sessionmaker

try:
    from sqlalchemy.ext.asyncio import async_sessionmaker as _async_sessionmaker
except ImportError:  # SQLAlchemy < 2.0
    _async_sessionmaker = None

Base = declarative_base()


class ProofJob(Base):
    """Persistent job record for asynchronous proof generation."""

    __tablename__ = "proof_jobs"

    proof_id = Column(String(64), primary_key=True)
    circuit_id = Column(String(128), nullable=False)
    status = Column(String(32), nullable=False)
    sealed_job_payload = Column(Text, nullable=True)
    input_fingerprint = Column(String(128), nullable=False)
    input_summary = Column(JSON, nullable=False, default=dict)
    sealed_purged_at = Column(DateTime(timezone=True), nullable=True)
    public_signals = Column(JSON, nullable=True)
    proof = Column(JSON, nullable=True)
    proof_path = Column(Text, nullable=True)
    error = Column(Text, nullable=True)
    meta = Column("metadata", JSON, nullable=False, default=dict)
    created_at = Column(DateTime(timezone=True), nullable=False)
    updated_at = Column(DateTime(timezone=True), nullable=False)


class AuditLog(Base):
    """Append-only audit chain table with signed hash links."""

    __tablename__ = "audit_log"

    id = Column(BigInteger, primary_key=True, autoincrement=True)
    timestamp = Column(DateTime(timezone=True), nullable=False)
    proof_id = Column(String(64), nullable=True)
    circuit_id = Column(String(128), nullable=False)
    status = Column(String(32), nullable=False)
    public_signals = Column(JSON, nullable=False)
    proof_hash = Column(String(128), nullable=False)
    previous_entry_hash = Column(String(128), nullable=False)
    entry_hash = Column(String(128), nullable=False)
    signature = Column(Text, nullable=False)
    key_version = Column(String(32), nullable=False)
    meta = Column("metadata", JSON, nullable=False, default=dict)
    error = Column(Text, nullable=True)


class SecurityEvent(Base):
    """Append-only security event telemetry for auth and incident forensics."""

    __tablename__ = "security_events"
    __table_args__ = (
        Index("ix_security_events_timestamp", "timestamp"),
        Index("ix_security_events_event_type", "event_type"),
    )

    id = Column(BigInteger, primary_key=True, autoincrement=True)
    timestamp = Column(DateTime(timezone=True), nullable=False)
    event_type = Column(String(64), nullable=False)
    outcome = Column(String(32), nullable=False)
    actor = Column(String(128), nullable=True)
    source_ip = Column(String(64), nullable=True)
    proof_id = Column(String(64), nullable=True)
    details = Column(JSON, nullable=False, default=dict)


@dataclass(frozen=True)
class AuditAppendInput:
    """Normalized shape for writing audit rows."""

    timestamp: datetime
    proof_id: str | None
    circuit_id: str
    status: str
    public_signals: list[Any]
    proof_hash: str
    previous_entry_hash: str
    entry_hash: str
    signature: str
    key_version: str
    meta: dict[str, Any]
    error: str | None


class Database:
    """Async persistence gateway for proof jobs and audit log operations."""

    def __init__(self, database_url: str) -> None:
        self.database_url = database_url
        self.engine: AsyncEngine = create_async_engine(database_url, future=True)
        if _async_sessionmaker is not None:
            self.session_factory = _async_sessionmaker(self.engine, expire_on_commit=False)
        else:
            self.session_factory = sessionmaker(
                self.engine,
                class_=AsyncSession,
                expire_on_commit=False,
            )

    async def init_models(self) -> None:
        """Create tables if they do not already exist."""
        async with self.engine.begin() as conn:
            await conn.run_sync(Base.metadata.create_all)

    async def create_proof_job(
        self,
        *,
        proof_id: str,
        circuit_id: str,
        status: str,
        sealed_job_payload: str,
        input_fingerprint: str,
        input_summary: dict[str, Any],
        metadata: dict[str, Any],
    ) -> ProofJob:
        """Insert and return a new proof job."""
        now = _utc_now()
        async with self.session_factory() as session:
            job = ProofJob(
                proof_id=proof_id,
                circuit_id=circuit_id,
                status=status,
                sealed_job_payload=sealed_job_payload,
                input_fingerprint=input_fingerprint,
                input_summary=input_summary,
                meta=metadata,
                created_at=now,
                updated_at=now,
            )
            session.add(job)
            await session.commit()
            await session.refresh(job)
            return job

    async def get_proof_job(self, proof_id: str) -> ProofJob | None:
        """Return a job by id or None if absent."""
        async with self.session_factory() as session:
            return await session.get(ProofJob, proof_id)

    async def list_proof_jobs(
        self,
        *,
        status: str | None = None,
        circuit_id: str | None = None,
        limit: int = 50,
    ) -> list[ProofJob]:
        """List recent jobs with optional status/circuit filters."""
        bounded_limit = min(max(limit, 1), 200)
        async with self.session_factory() as session:
            query = select(ProofJob)
            if status is not None:
                query = query.where(ProofJob.status == status)
            if circuit_id is not None:
                query = query.where(ProofJob.circuit_id == circuit_id)
            query = query.order_by(desc(ProofJob.created_at)).limit(bounded_limit)
            result = await session.execute(query)
            return list(result.scalars().all())

    async def update_proof_job(
        self,
        *,
        proof_id: str,
        status: str,
        public_signals: list[Any] | None = None,
        proof: dict[str, Any] | None = None,
        proof_path: str | None = None,
        error: str | None = None,
        metadata_patch: dict[str, Any] | None = None,
    ) -> ProofJob | None:
        """Apply status/result updates to an existing job."""
        async with self.session_factory() as session:
            job = await session.get(ProofJob, proof_id)
            if job is None:
                return None
            now = _utc_now()
            job.status = status
            job.updated_at = now
            if public_signals is not None:
                job.public_signals = public_signals
            if proof is not None:
                job.proof = proof
            if proof_path is not None:
                job.proof_path = proof_path
            if error is not None:
                job.error = error
            if metadata_patch:
                merged = dict(job.meta or {})
                merged.update(metadata_patch)
                job.meta = merged
            await session.commit()
            await session.refresh(job)
            return job

    async def purge_sealed_job_payload(self, *, proof_id: str) -> ProofJob | None:
        """Delete encrypted request payload from a completed/failed job."""
        async with self.session_factory() as session:
            job = await session.get(ProofJob, proof_id)
            if job is None:
                return None
            now = _utc_now()
            job.sealed_job_payload = None
            job.sealed_purged_at = now
            job.updated_at = now
            await session.commit()
            await session.refresh(job)
            return job

    async def append_audit_row(self, payload: AuditAppendInput | dict[str, Any]) -> AuditLog:
        """Append one audit row, enforcing chain continuity under DB lock."""
        normalized = _normalize_audit_payload(payload)
        async with self.session_factory() as session:
            # Serialize all audit-link writes across workers/processes.
            await session.execute(text("SELECT pg_advisory_xact_lock(:lock_id)"), {"lock_id": 2403192601})

            latest_result = await session.execute(
                select(AuditLog).order_by(AuditLog.id.desc()).limit(1)
            )
            latest = latest_result.scalar_one_or_none()
            expected_previous = latest.entry_hash if latest is not None else ""
            if normalized.previous_entry_hash != expected_previous:
                raise RuntimeError("audit_chain_conflict")

            row = AuditLog(
                timestamp=normalized.timestamp,
                proof_id=normalized.proof_id,
                circuit_id=normalized.circuit_id,
                status=normalized.status,
                public_signals=normalized.public_signals,
                proof_hash=normalized.proof_hash,
                previous_entry_hash=normalized.previous_entry_hash,
                entry_hash=normalized.entry_hash,
                signature=normalized.signature,
                key_version=normalized.key_version,
                meta=normalized.meta,
                error=normalized.error,
            )
            session.add(row)
            await session.commit()
            await session.refresh(row)
            return row

    async def get_latest_audit_row(self) -> AuditLog | None:
        """Return latest audit row by sequence id."""
        async with self.session_factory() as session:
            query = select(AuditLog).order_by(AuditLog.id.desc()).limit(1)
            result = await session.execute(query)
            return result.scalar_one_or_none()

    async def list_audit_rows(self) -> list[AuditLog]:
        """Return full audit chain ordered by id ascending."""
        async with self.session_factory() as session:
            query = select(AuditLog).order_by(AuditLog.id.asc())
            result = await session.execute(query)
            return list(result.scalars().all())

    async def list_audit_rows_for_proof(self, *, proof_id: str) -> list[AuditLog]:
        """Return audit rows for one proof id ordered by id ascending."""
        async with self.session_factory() as session:
            query = (
                select(AuditLog)
                .where(AuditLog.proof_id == proof_id)
                .order_by(AuditLog.id.asc())
            )
            result = await session.execute(query)
            return list(result.scalars().all())

    async def count_jobs_by_status(self, status: str) -> int:
        """Return number of jobs with a given status."""
        async with self.session_factory() as session:
            query = select(func.count()).select_from(ProofJob).where(ProofJob.status == status)
            result = await session.execute(query)
            return int(result.scalar_one())

    async def append_security_event(
        self,
        *,
        event_type: str,
        outcome: str,
        actor: str | None = None,
        source_ip: str | None = None,
        proof_id: str | None = None,
        details: dict[str, Any] | None = None,
    ) -> SecurityEvent:
        """Persist one structured security event row."""
        async with self.session_factory() as session:
            row = SecurityEvent(
                timestamp=_utc_now(),
                event_type=event_type,
                outcome=outcome,
                actor=actor,
                source_ip=source_ip,
                proof_id=proof_id,
                details=details or {},
            )
            session.add(row)
            await session.commit()
            await session.refresh(row)
            return row


def _utc_now() -> datetime:
    """Return timezone-aware UTC timestamp."""
    return datetime.now(timezone.utc)


def _normalize_audit_payload(payload: AuditAppendInput | dict[str, Any]) -> AuditAppendInput:
    """Normalize dict payloads to AuditAppendInput dataclass."""
    if isinstance(payload, AuditAppendInput):
        return payload
    return AuditAppendInput(
        timestamp=payload["timestamp"],
        proof_id=payload.get("proof_id"),
        circuit_id=payload["circuit_id"],
        status=payload["status"],
        public_signals=payload.get("public_signals", []),
        proof_hash=payload.get("proof_hash", ""),
        previous_entry_hash=payload.get("previous_entry_hash", ""),
        entry_hash=payload["entry_hash"],
        signature=payload["signature"],
        key_version=payload.get("key_version", "0"),
        meta=payload.get("meta", {}),
        error=payload.get("error"),
    )
