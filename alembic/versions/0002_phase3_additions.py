"""phase 3 additions: template/region fields + submission_answers table

Revision ID: 0002
Revises: 0001
Create Date: 2026-04-13

Adds:
  - exams.template_spec_json        (nullable Text) — Phase 4 template spec
  - exam_questions.region_json      (nullable Text) — Phase 5 region cropping
  - submission_answers table        — Phase 3 structured OCR results per page/question
"""
from __future__ import annotations

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

revision: str = "0002"
down_revision: Union[str, None] = "0001"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    # -- exams: add template_spec_json --
    op.add_column("exams", sa.Column("template_spec_json", sa.Text, nullable=True))

    # -- exam_questions: add region_json --
    op.add_column("exam_questions", sa.Column("region_json", sa.Text, nullable=True))

    # -- submission_answers (new table) --
    op.create_table(
        "submission_answers",
        sa.Column("id", sa.Integer, primary_key=True, autoincrement=True),
        sa.Column(
            "submission_id",
            sa.Integer,
            sa.ForeignKey("submissions.id"),
            nullable=False,
        ),
        sa.Column(
            "question_id",
            sa.Integer,
            sa.ForeignKey("exam_questions.id"),
            nullable=True,
        ),
        sa.Column("page_number", sa.Integer, nullable=False, default=1),
        sa.Column("ocr_text", sa.Text, nullable=True),
        sa.Column("boxes_json", sa.Text, nullable=True),
        sa.Column("status", sa.String(32), nullable=False, default="pending"),
        sa.Column("created_at", sa.DateTime, nullable=False),
        sa.Column("updated_at", sa.DateTime, nullable=False),
    )
    op.create_index(
        "ix_submission_answers_submission_id", "submission_answers", ["submission_id"]
    )
    op.create_index(
        "ix_submission_answers_question_id", "submission_answers", ["question_id"]
    )


def downgrade() -> None:
    op.drop_table("submission_answers")
    op.drop_column("exam_questions", "region_json")
    op.drop_column("exams", "template_spec_json")
