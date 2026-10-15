"""teacher "mark reviewed" on answers

submission_answers.reviewed_at — set when the teacher explicitly marks an answer
as reviewed (naive UTC). NULL = not marked. It is purely a review marker: it
never changes the answer's status, score, or any grading data. Together with a
reviewed flag or a teacher score override it takes an answer out of the exam's
review queue.

Revision ID: 0016
Revises: 0015
Create Date: 2026-10-11
"""
from alembic import op
import sqlalchemy as sa

revision = "0016"
down_revision = "0015"
branch_labels = None
depends_on = None


def upgrade() -> None:
    with op.batch_alter_table("submission_answers") as b:
        b.add_column(sa.Column("reviewed_at", sa.DateTime(), nullable=True))


def downgrade() -> None:
    with op.batch_alter_table("submission_answers") as b:
        b.drop_column("reviewed_at")
