"""Add groq_confidence column to submission_answers (Phase 16 grading engine).

Revision ID: 0006
Revises: 0005
Create Date: 2026-04-15
"""
from __future__ import annotations

import sqlalchemy as sa
from alembic import op

revision = "0006"
down_revision = "0005"
branch_labels = None
depends_on = None


def upgrade() -> None:
    with op.batch_alter_table("submission_answers") as batch_op:
        batch_op.add_column(
            sa.Column("groq_confidence", sa.Float(), nullable=True)
        )


def downgrade() -> None:
    with op.batch_alter_table("submission_answers") as batch_op:
        batch_op.drop_column("groq_confidence")
