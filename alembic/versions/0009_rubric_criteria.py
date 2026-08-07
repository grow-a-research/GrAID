"""add structured rubric criteria + per-criterion AI scores

Revision ID: 0009
Revises: 0008
Create Date: 2026-08-07
"""
from alembic import op
import sqlalchemy as sa

revision = "0009"
down_revision = "0008"
branch_labels = None
depends_on = None


def upgrade() -> None:
    with op.batch_alter_table("exam_questions") as batch_op:
        batch_op.add_column(sa.Column("rubric_criteria_json", sa.Text(), nullable=True))
    with op.batch_alter_table("submission_answers") as batch_op:
        batch_op.add_column(sa.Column("ai_criteria_scores_json", sa.Text(), nullable=True))


def downgrade() -> None:
    with op.batch_alter_table("submission_answers") as batch_op:
        batch_op.drop_column("ai_criteria_scores_json")
    with op.batch_alter_table("exam_questions") as batch_op:
        batch_op.drop_column("rubric_criteria_json")
