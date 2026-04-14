"""Add omr_confidence column to submission_answers (Phase 13 OMR engine).

Revision ID: 0005
Revises: 0004
Create Date: 2026-04-14
"""
from __future__ import annotations

import sqlalchemy as sa
from alembic import op

revision = "0005"
down_revision = "0004"
branch_labels = None
depends_on = None


def upgrade() -> None:
    with op.batch_alter_table("submission_answers") as batch_op:
        batch_op.add_column(
            sa.Column("omr_confidence", sa.Float(), nullable=True)
        )


def downgrade() -> None:
    with op.batch_alter_table("submission_answers") as batch_op:
        batch_op.drop_column("omr_confidence")
