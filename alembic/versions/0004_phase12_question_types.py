"""Phase 12: new question type columns on exam_questions

Revision ID: 0004
Revises: 0003
Create Date: 2026-04-14

Adds to exam_questions:
  - choices_json    TEXT nullable  — JSON list of MCQ choice strings
  - correct_answer  TEXT nullable  — letter (MCQ), 'True'/'False' (tf), string (identification)
"""
from __future__ import annotations

import sqlalchemy as sa
from alembic import op

revision = "0004"
down_revision = "0003"
branch_labels = None
depends_on = None


def upgrade() -> None:
    with op.batch_alter_table("exam_questions") as batch_op:
        batch_op.add_column(sa.Column("choices_json", sa.Text(), nullable=True))
        batch_op.add_column(sa.Column("correct_answer", sa.Text(), nullable=True))


def downgrade() -> None:
    with op.batch_alter_table("exam_questions") as batch_op:
        batch_op.drop_column("correct_answer")
        batch_op.drop_column("choices_json")
