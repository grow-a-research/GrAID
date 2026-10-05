"""store the numeric OCR line confidence alongside the low_confidence flag

Needed by the combined OCR + grading confidence flag: the boolean alone
cannot be recombined with groq_confidence or reported per answer.

Nullable with no backfill on purpose — answers OCR'd before this column
existed have no recorded confidence, and inventing one would put fabricated
numbers into the flag statistics. NULL reads as "unknown", never as "low".

Revision ID: 0012
Revises: 0011
Create Date: 2026-09-22
"""
from alembic import op
import sqlalchemy as sa

revision = "0012"
down_revision = "0011"
branch_labels = None
depends_on = None


def upgrade() -> None:
    with op.batch_alter_table("submission_answers") as batch_op:
        batch_op.add_column(sa.Column("ocr_confidence", sa.Float(), nullable=True))


def downgrade() -> None:
    with op.batch_alter_table("submission_answers") as batch_op:
        batch_op.drop_column("ocr_confidence")
