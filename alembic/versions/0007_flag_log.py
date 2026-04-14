"""Add flag_log table for Phase 17 RQ4 precision/recall tracking.

Revision ID: 0007
Revises: 0006
Create Date: 2026-04-15
"""
from __future__ import annotations

import sqlalchemy as sa
from alembic import op

revision = "0007"
down_revision = "0006"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "flag_log",
        sa.Column("id", sa.Integer(), autoincrement=True, nullable=False),
        sa.Column("submission_answer_id", sa.Integer(), nullable=False),
        sa.Column("flag_reason", sa.String(length=64), nullable=False),
        sa.Column("auto_flagged", sa.Boolean(), nullable=False, server_default="1"),
        sa.Column("auto_flagged_at", sa.DateTime(), nullable=False),
        sa.Column("reviewed_by", sa.String(length=255), nullable=True),
        sa.Column("review_decision", sa.String(length=32), nullable=True),
        sa.Column("reviewed_at", sa.DateTime(), nullable=True),
        sa.Column("created_at", sa.DateTime(), nullable=False),
        sa.ForeignKeyConstraint(["submission_answer_id"], ["submission_answers.id"]),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("submission_answer_id"),
    )
    op.create_index("ix_flag_log_submission_answer_id", "flag_log", ["submission_answer_id"])


def downgrade() -> None:
    op.drop_index("ix_flag_log_submission_answer_id", table_name="flag_log")
    op.drop_table("flag_log")
