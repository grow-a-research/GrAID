"""teacher notifications and automatic grading after the deadline

notifications          — in-app notifications for a teacher.
exams.auto_grade       — teacher switch: grade submitted papers automatically
                         once the deadline passes. Off for every existing exam.
exams.auto_grade_started_at / _finished_at — when the automatic run began and
                         when its queue drained (NULL until then).

Revision ID: 0017
Revises: 0016
Create Date: 2026-10-14
"""
from alembic import op
import sqlalchemy as sa

revision = "0017"
down_revision = "0016"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "notifications",
        sa.Column("id", sa.Integer(), primary_key=True, autoincrement=True),
        sa.Column("teacher_id", sa.Integer(), sa.ForeignKey("teachers.id"), nullable=False),
        sa.Column("kind", sa.String(32), nullable=False),
        sa.Column("title", sa.String(255), nullable=False),
        sa.Column("body", sa.Text(), nullable=False, server_default=""),
        sa.Column("exam_id", sa.Integer(), nullable=True),
        sa.Column("link_tab", sa.String(32), nullable=True),
        sa.Column("count", sa.Integer(), nullable=False, server_default="1"),
        sa.Column("created_at", sa.DateTime(), nullable=False),
        sa.Column("read_at", sa.DateTime(), nullable=True),
    )
    op.create_index("ix_notifications_teacher_id", "notifications", ["teacher_id"])
    op.create_index("ix_notifications_exam_id", "notifications", ["exam_id"])

    with op.batch_alter_table("exams") as b:
        b.add_column(sa.Column("auto_grade", sa.Boolean(), nullable=False, server_default=sa.false()))
        b.add_column(sa.Column("auto_grade_started_at", sa.DateTime(), nullable=True))
        b.add_column(sa.Column("auto_grade_finished_at", sa.DateTime(), nullable=True))


def downgrade() -> None:
    with op.batch_alter_table("exams") as b:
        b.drop_column("auto_grade_finished_at")
        b.drop_column("auto_grade_started_at")
        b.drop_column("auto_grade")
    op.drop_index("ix_notifications_exam_id", table_name="notifications")
    op.drop_index("ix_notifications_teacher_id", table_name="notifications")
    op.drop_table("notifications")
