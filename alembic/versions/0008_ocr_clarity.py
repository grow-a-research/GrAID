"""add ocr_clarity to submission_answers

Revision ID: 0008
Revises: 0007
Create Date: 2026-04-15
"""
from alembic import op
import sqlalchemy as sa

revision = "0008"
down_revision = "0007"
branch_labels = None
depends_on = None


def upgrade() -> None:
    with op.batch_alter_table("submission_answers") as batch_op:
        batch_op.add_column(sa.Column("ocr_clarity", sa.Float(), nullable=True))


def downgrade() -> None:
    with op.batch_alter_table("submission_answers") as batch_op:
        batch_op.drop_column("ocr_clarity")
