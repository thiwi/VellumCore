from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Any

from sqlalchemy import JSON, BigInteger, DateTime, String, Text, select
from sqlalchemy.ext.asyncio import AsyncEngine, AsyncSession, create_async_engine
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column, sessionmaker

try:
    from sqlalchemy.ext.asyncio import async_sessionmaker
except ImportError:  # pragma: no cover - compatibility for older SQLAlchemy
    async_sessionmaker = None  # type: ignore[assignment]


class Base(DeclarativeBase):
    pass


class ProofJob(Base):
    __tablename__ = "proof_jobs"

    proof_id: Mapped[str] = mapped_column(String(64), primary_key=True)
    circuit_id: Mapped[str] = mapped_column(String(128), nullable=False)
    status: Mapped[str] = mapped_column(String(32), nullable=False)
    request_payload: Mapped[dict[str, Any]] = mapped_column(JSON, nullable=False)
    private_input: Mapped[dict[str, Any] | None] = mapped_column(JSON, nullable=True)
    source_ref: Mapped[str | None] = mapped_column(String(256), nullable=True)
    public_signals: Mapped[list[Any] | None] = mapped_column(JSON, nullable=True)
    proof: Mapped[dict[str, Any] | None] = mapped_column(JSON, nullable=True)
    proof_path: Mapped[str | None] = mapped_column(Text, nullable=True)
    error: Mapped[str | None] = mapped_column(Text, nullable=True)
    meta: Mapped[dict[str, Any]] = mapped_column("metadata", JSON, nullable=False, default=dict)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)


class AuditLog(Base):
    __tablename__ = "audit_log"

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True, autoincrement=True)
    timestamp: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    proof_id: Mapped[str | None] = mapped_column(String(64), nullable=True)
    circuit_id: Mapped[str] = mapped_column(String(128), nullable=False)
    status: Mapped[str] = mapped_column(String(32), nullable=False)
    public_signals: Mapped[list[Any]] = mapped_column(JSON, nullable=False)
    proof_hash: Mapped[str] = mapped_column(String(128), nullable=False)
    previous_entry_hash: Mapped[str] = mapped_column(String(128), nullable=False)
    entry_hash: Mapped[str] = mapped_column(String(128), nullable=False)
    signature: Mapped[str] = mapped_column(Text, nullable=False)
    key_version: Mapped[str] = mapped_column(String(32), nullable=False)
    meta: Mapped[dict[str, Any]] = mapped_column("metadata", JSON, nullable=False, default=dict)
    error: Mapped[str | None] = mapped_column(Text, nullable=True)


@dataclass(frozen=True)
class AuditAppendInput:
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
    def __init__(self, database_url: str) -> None:
        self.database_url = database_url
        self.engine: AsyncEngine = create_async_engine(database_url, future=True)
        if async_sessionmaker is not None:
            self.session_factory = async_sessionmaker(self.engine, expire_on_commit=False)
        else:  # pragma: no cover - compatibility for older SQLAlchemy
            self.session_factory = sessionmaker(
                bind=self.engine,
                class_=AsyncSession,
                expire_on_commit=False,
            )

    async def init_models(self) -> None:
        async with self.engine.begin() as conn:
            await conn.run_sync(Base.metadata.create_all)

    async def create_proof_job(
        self,
        *,
        proof_id: str,
        circuit_id: str,
        status: str,
        request_payload: dict[str, Any],
        private_input: dict[str, Any] | None,
        source_ref: str | None,
        metadata: dict[str, Any],
    ) -> ProofJob:
        now = _utc_now()
        async with self.session_factory() as session:
            job = ProofJob(
                proof_id=proof_id,
                circuit_id=circuit_id,
                status=status,
                request_payload=request_payload,
                private_input=private_input,
                source_ref=source_ref,
                meta=metadata,
                created_at=now,
                updated_at=now,
            )
            session.add(job)
            await session.commit()
            await session.refresh(job)
            return job

    async def get_proof_job(self, proof_id: str) -> ProofJob | None:
        async with self.session_factory() as session:
            return await session.get(ProofJob, proof_id)

    async def update_proof_job(
        self,
        *,
        proof_id: str,
        status: str,
        public_signals: list[Any] | None = None,
        proof: dict[str, Any] | None = None,
        proof_path: str | None = None,
        error: str | None = None,
    ) -> ProofJob | None:
        async with self.session_factory() as session:
            job = await session.get(ProofJob, proof_id)
            if job is None:
                return None
            job.status = status
            job.updated_at = _utc_now()
            if public_signals is not None:
                job.public_signals = public_signals
            if proof is not None:
                job.proof = proof
            if proof_path is not None:
                job.proof_path = proof_path
            if error is not None:
                job.error = error
            await session.commit()
            await session.refresh(job)
            return job

    async def append_audit_row(self, payload: AuditAppendInput | dict[str, Any]) -> AuditLog:
        normalized = _normalize_audit_payload(payload)
        async with self.session_factory() as session:
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
        async with self.session_factory() as session:
            query = select(AuditLog).order_by(AuditLog.id.desc()).limit(1)
            result = await session.execute(query)
            return result.scalar_one_or_none()

    async def list_audit_rows(self) -> list[AuditLog]:
        async with self.session_factory() as session:
            query = select(AuditLog).order_by(AuditLog.id.asc())
            result = await session.execute(query)
            return list(result.scalars().all())

    async def count_jobs_by_status(self, status: str) -> int:
        async with self.session_factory() as session:
            query = select(ProofJob).where(ProofJob.status == status)
            result = await session.execute(query)
            return len(result.scalars().all())


class DatabaseSession:
    def __init__(self, db: Database) -> None:
        self.db = db

    async def __aenter__(self) -> AsyncSession:
        self.session = self.db.session_factory()
        return self.session

    async def __aexit__(self, exc_type, exc, tb) -> None:  # type: ignore[no-untyped-def]
        await self.session.close()


def _utc_now() -> datetime:
    return datetime.now(timezone.utc)


def _normalize_audit_payload(payload: AuditAppendInput | dict[str, Any]) -> AuditAppendInput:
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
