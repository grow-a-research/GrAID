"""Phase 6: AI grading columns on submission_answers

Revision ID: 0003
Revises: 0002
Create Date: 2026-04-13

Adds to submission_answers:
  - ai_score         REAL nullable  — Groq-assigned score
  - ai_feedback      TEXT nullable  — constructive written evaluation
  - cer              REAL nullable  — character error rate (vs reference)
  - wer              REAL nullable  — word error rate (vs reference)
  - teacher_score    REAL nullable  — teacher override score
  - teacher_note     TEXT nullable  — teacher override justification
"""
from __future__ import annotations

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

revision: str = "0003"
down_revision: Union[str, None] = "0002"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column("submission_answers", sa.Column("ai_score",      sa.Float,  nullable=True))
    op.add_column("submission_answers", sa.Column("ai_feedback",   sa.Text,   nullable=True))
    op.add_column("submission_answers", sa.Column("cer",           sa.Float,  nullable=True))
    op.add_column("submission_answers", sa.Column("wer",           sa.Float,  nullable=True))
    op.add_column("submission_answers", sa.Column("teacher_score", sa.Float,  nullable=True))
    op.add_column("submission_answers", sa.Column("teacher_note",  sa.Text,   nullable=True))


def downgrade() -> None:
    op.drop_column("submission_answers", "teacher_note")
    op.drop_column("submission_answers", "teacher_score")
    op.drop_column("submission_answers", "wer")
    op.drop_column("submission_answers", "cer")
    op.drop_column("submission_answers", "ai_feedback")
    op.drop_column("submission_answers", "ai_score")
