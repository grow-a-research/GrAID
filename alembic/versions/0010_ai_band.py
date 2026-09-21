"""add suggested performance band from the ordinal classification model

Revision ID: 0010
Revises: 0009
Create Date: 2026-09-19
"""
from alembic import op
import sqlalchemy as sa

revision = "0010"
down_revision = "0009"
branch_labels = None
depends_on = None


def upgrade() -> None:
    with op.batch_alter_table("submission_answers") as batch_op:
        batch_op.add_column(sa.Column("ai_band", sa.String(16), nullable=True))
        batch_op.add_column(sa.Column("ai_band_probs_json", sa.Text(), nullable=True))
        batch_op.add_column(sa.Column("ai_spread", sa.Float(), nullable=True))
        batch_op.add_column(sa.Column("ai_band_model_version", sa.String(64), nullable=True))


def downgrade() -> None:
    with op.batch_alter_table("submission_answers") as batch_op:
        batch_op.drop_column("ai_band_model_version")
        batch_op.drop_column("ai_spread")
        batch_op.drop_column("ai_band_probs_json")
        batch_op.drop_column("ai_band")
