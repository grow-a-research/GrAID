"""add teacher-set case sensitivity for identification exact-match scoring

Revision ID: 0011
Revises: 0010
Create Date: 2026-09-19
"""
from alembic import op
import sqlalchemy as sa

revision = "0011"
down_revision = "0010"
branch_labels = None
depends_on = None


def upgrade() -> None:
    with op.batch_alter_table("exam_questions") as batch_op:
        batch_op.add_column(
            sa.Column("case_sensitive", sa.Boolean(), nullable=False, server_default=sa.false())
        )


def downgrade() -> None:
    with op.batch_alter_table("exam_questions") as batch_op:
        batch_op.drop_column("case_sensitive")
