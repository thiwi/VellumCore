"""initial vellum schema

Revision ID: 0001_init
Revises: 
Create Date: 2026-03-19
"""

from alembic import op
import sqlalchemy as sa


revision = "0001_init"
down_revision = None
branch_labels = None
depends_on = None


def upgrade() -> None:
    """Create initial proof_jobs and audit_log tables."""
    op.create_table(
        "proof_jobs",
        sa.Column("proof_id", sa.String(length=64), primary_key=True),
        sa.Column("circuit_id", sa.String(length=128), nullable=False),
        sa.Column("status", sa.String(length=32), nullable=False),
        sa.Column("request_payload", sa.JSON(), nullable=False),
        sa.Column("private_input", sa.JSON(), nullable=True),
        sa.Column("public_signals", sa.JSON(), nullable=True),
        sa.Column("proof", sa.JSON(), nullable=True),
        sa.Column("proof_path", sa.Text(), nullable=True),
        sa.Column("error", sa.Text(), nullable=True),
        sa.Column("metadata", sa.JSON(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
    )

    op.create_table(
        "audit_log",
        sa.Column("id", sa.BigInteger(), primary_key=True, autoincrement=True),
        sa.Column("timestamp", sa.DateTime(timezone=True), nullable=False),
        sa.Column("proof_id", sa.String(length=64), nullable=True),
        sa.Column("circuit_id", sa.String(length=128), nullable=False),
        sa.Column("status", sa.String(length=32), nullable=False),
        sa.Column("public_signals", sa.JSON(), nullable=False),
        sa.Column("proof_hash", sa.String(length=128), nullable=False),
        sa.Column("previous_entry_hash", sa.String(length=128), nullable=False),
        sa.Column("entry_hash", sa.String(length=128), nullable=False),
        sa.Column("signature", sa.Text(), nullable=False),
        sa.Column("key_version", sa.String(length=32), nullable=False),
        sa.Column("metadata", sa.JSON(), nullable=False),
        sa.Column("error", sa.Text(), nullable=True),
    )


def downgrade() -> None:
    """Drop initial schema tables."""
    op.drop_table("audit_log")
    op.drop_table("proof_jobs")
