"""initial schema

Revision ID: 0001
Revises:
Create Date: 2026-04-13

Creates all tables that were originally managed by Base.metadata.create_all().
If the app previously ran with create_all() and tables already exist,
database.init_db() will stamp the DB at this revision before upgrading,
so this migration is skipped and only 0002 onward are applied.
"""
from __future__ import annotations

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

revision: str = "0001"
down_revision: Union[str, None] = None
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        "course_classes",
        sa.Column("id", sa.Integer, primary_key=True, autoincrement=True),
        sa.Column("code", sa.String(64), nullable=False, unique=True),
        sa.Column("name", sa.String(255), nullable=False),
        sa.Column("created_at", sa.DateTime, nullable=False),
    )
    op.create_index("ix_course_classes_code", "course_classes", ["code"])

    op.create_table(
        "students",
        sa.Column("id", sa.Integer, primary_key=True, autoincrement=True),
        sa.Column("student_id", sa.String(64), nullable=False, unique=True),
        sa.Column("full_name", sa.String(255), nullable=False),
        sa.Column("email", sa.String(255), nullable=True),
    )
    op.create_index("ix_students_student_id", "students", ["student_id"])

    op.create_table(
        "enrollments",
        sa.Column("id", sa.Integer, primary_key=True, autoincrement=True),
        sa.Column("class_id", sa.Integer, sa.ForeignKey("course_classes.id"), nullable=False),
        sa.Column("student_id", sa.Integer, sa.ForeignKey("students.id"), nullable=False),
        sa.Column("enrolled_at", sa.DateTime, nullable=False),
        sa.UniqueConstraint("class_id", "student_id", name="uq_enrollment_class_student"),
    )
    op.create_index("ix_enrollments_class_id", "enrollments", ["class_id"])
    op.create_index("ix_enrollments_student_id", "enrollments", ["student_id"])

    op.create_table(
        "exams",
        sa.Column("id", sa.Integer, primary_key=True, autoincrement=True),
        sa.Column("class_id", sa.Integer, sa.ForeignKey("course_classes.id"), nullable=False),
        sa.Column("exam_code", sa.String(64), nullable=False),
        sa.Column("title", sa.String(255), nullable=False),
        sa.Column("description", sa.Text, nullable=True),
        sa.Column("created_at", sa.DateTime, nullable=False),
        sa.UniqueConstraint("class_id", "exam_code", name="uq_exam_class_code"),
    )
    op.create_index("ix_exams_class_id", "exams", ["class_id"])
    op.create_index("ix_exams_exam_code", "exams", ["exam_code"])

    op.create_table(
        "exam_questions",
        sa.Column("id", sa.Integer, primary_key=True, autoincrement=True),
        sa.Column("exam_id", sa.Integer, sa.ForeignKey("exams.id"), nullable=False),
        sa.Column("order_index", sa.Integer, nullable=False, default=1),
        sa.Column("prompt", sa.Text, nullable=False),
        sa.Column("question_type", sa.String(32), nullable=False, default="essay"),
        sa.Column("rubric_text", sa.Text, nullable=True),
        sa.Column("max_points", sa.Float, nullable=False, default=10.0),
    )
    op.create_index("ix_exam_questions_exam_id", "exam_questions", ["exam_id"])

    op.create_table(
        "submissions",
        sa.Column("id", sa.Integer, primary_key=True, autoincrement=True),
        sa.Column("exam_id", sa.Integer, sa.ForeignKey("exams.id"), nullable=False),
        sa.Column("student_id", sa.Integer, sa.ForeignKey("students.id"), nullable=False),
        sa.Column("status", sa.String(32), nullable=False, default="draft"),
        sa.Column("created_at", sa.DateTime, nullable=False),
        sa.Column("updated_at", sa.DateTime, nullable=False),
        sa.UniqueConstraint("exam_id", "student_id", name="uq_submission_exam_student"),
    )
    op.create_index("ix_submissions_exam_id", "submissions", ["exam_id"])
    op.create_index("ix_submissions_student_id", "submissions", ["student_id"])

    op.create_table(
        "submission_files",
        sa.Column("id", sa.Integer, primary_key=True, autoincrement=True),
        sa.Column("submission_id", sa.Integer, sa.ForeignKey("submissions.id"), nullable=False),
        sa.Column("page_number", sa.Integer, nullable=False, default=1),
        sa.Column("original_filename", sa.String(512), nullable=False),
        sa.Column("stored_path", sa.String(1024), nullable=False),
    )
    op.create_index("ix_submission_files_submission_id", "submission_files", ["submission_id"])


def downgrade() -> None:
    op.drop_table("submission_files")
    op.drop_table("submissions")
    op.drop_table("exam_questions")
    op.drop_table("exams")
    op.drop_table("enrollments")
    op.drop_table("students")
    op.drop_table("course_classes")
