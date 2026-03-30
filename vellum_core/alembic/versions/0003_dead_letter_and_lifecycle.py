"""dead-letter queue and lifecycle support

Revision ID: 0003_dead_letter_and_lifecycle
Revises: 0002_security_hardening
Create Date: 2026-03-30
"""

from alembic import op
import sqlalchemy as sa


revision = "0003_dead_letter_and_lifecycle"
down_revision = "0002_security_hardening"
branch_labels = None
depends_on = None


def upgrade() -> None:
    """Create DLQ table and retention helper indexes."""
    op.create_table(
        "dead_letter_jobs",
        sa.Column("id", sa.BigInteger(), primary_key=True, autoincrement=True),
        sa.Column("proof_id", sa.String(length=64), nullable=False, unique=True),
        sa.Column("circuit_id", sa.String(length=128), nullable=False),
        sa.Column("error_class", sa.String(length=64), nullable=False),
        sa.Column("retryable", sa.Boolean(), nullable=False, server_default=sa.text("false")),
        sa.Column("failure_reason", sa.String(length=64), nullable=False),
        sa.Column("error_message", sa.Text(), nullable=False),
        sa.Column("attempt_count", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("max_attempts", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("triage_details", sa.JSON(), nullable=False, server_default=sa.text("'{}'::json")),
        sa.Column("job_metadata", sa.JSON(), nullable=False, server_default=sa.text("'{}'::json")),
        sa.Column("sealed_rerun_payload", sa.Text(), nullable=True),
        sa.Column("status", sa.String(length=32), nullable=False, server_default="open"),
        sa.Column("rerun_proof_id", sa.String(length=64), nullable=True),
        sa.Column("rerun_requested_by", sa.String(length=128), nullable=True),
        sa.Column("rerun_reason", sa.Text(), nullable=True),
        sa.Column("triaged_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("requeued_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
    )
    op.create_index("ix_dead_letter_jobs_status", "dead_letter_jobs", ["status"])
    op.create_index("ix_dead_letter_jobs_created_at", "dead_letter_jobs", ["created_at"])

    op.create_index(
        "ix_proof_jobs_status_updated_at",
        "proof_jobs",
        ["status", "updated_at"],
    )


def downgrade() -> None:
    """Drop DLQ table and lifecycle indexes."""
    op.drop_index("ix_proof_jobs_status_updated_at", table_name="proof_jobs")
    op.drop_index("ix_dead_letter_jobs_created_at", table_name="dead_letter_jobs")
    op.drop_index("ix_dead_letter_jobs_status", table_name="dead_letter_jobs")
    op.drop_table("dead_letter_jobs")
