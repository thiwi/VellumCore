"""security hardening schema changes

Revision ID: 0002_security_hardening
Revises: 0001_init
Create Date: 2026-03-21
"""

from alembic import op
import sqlalchemy as sa


revision = "0002_security_hardening"
down_revision = "0001_init"
branch_labels = None
depends_on = None


def upgrade() -> None:
    """Migrate proof job payload storage and add security event table."""
    op.add_column("proof_jobs", sa.Column("sealed_job_payload", sa.Text(), nullable=True))
    op.add_column("proof_jobs", sa.Column("input_fingerprint", sa.String(length=128), nullable=True))
    op.add_column("proof_jobs", sa.Column("input_summary", sa.JSON(), nullable=True))
    op.add_column("proof_jobs", sa.Column("sealed_purged_at", sa.DateTime(timezone=True), nullable=True))

    op.execute(
        "UPDATE proof_jobs "
        "SET input_fingerprint = md5(proof_id), input_summary = '{}'::json "
        "WHERE input_fingerprint IS NULL OR input_summary IS NULL"
    )
    op.alter_column("proof_jobs", "input_fingerprint", nullable=False)
    op.alter_column("proof_jobs", "input_summary", nullable=False)

    op.drop_column("proof_jobs", "private_input")
    op.drop_column("proof_jobs", "request_payload")

    op.create_table(
        "security_events",
        sa.Column("id", sa.BigInteger(), primary_key=True, autoincrement=True),
        sa.Column("timestamp", sa.DateTime(timezone=True), nullable=False),
        sa.Column("event_type", sa.String(length=64), nullable=False),
        sa.Column("outcome", sa.String(length=32), nullable=False),
        sa.Column("actor", sa.String(length=128), nullable=True),
        sa.Column("source_ip", sa.String(length=64), nullable=True),
        sa.Column("proof_id", sa.String(length=64), nullable=True),
        sa.Column("details", sa.JSON(), nullable=False),
    )
    op.create_index("ix_security_events_timestamp", "security_events", ["timestamp"])
    op.create_index("ix_security_events_event_type", "security_events", ["event_type"])


def downgrade() -> None:
    """Rollback security hardening schema changes."""
    op.drop_index("ix_security_events_event_type", table_name="security_events")
    op.drop_index("ix_security_events_timestamp", table_name="security_events")
    op.drop_table("security_events")

    op.add_column("proof_jobs", sa.Column("request_payload", sa.JSON(), nullable=True))
    op.add_column("proof_jobs", sa.Column("private_input", sa.JSON(), nullable=True))
    op.drop_column("proof_jobs", "sealed_purged_at")
    op.drop_column("proof_jobs", "input_summary")
    op.drop_column("proof_jobs", "input_fingerprint")
    op.drop_column("proof_jobs", "sealed_job_payload")
