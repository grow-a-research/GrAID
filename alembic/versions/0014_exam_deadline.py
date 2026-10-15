"""exam deadlines and submission timestamps

exams.due_at        — optional deadline, stored as naive UTC. NULL = no deadline,
                      so every existing exam keeps behaving exactly as before.
submissions.submitted_at — when the student pressed Submit (naive UTC). NULL for
                      anything submitted before this column existed, which is
                      never treated as late.

Revision ID: 0014
Revises: 0013
Create Date: 2026-10-11
"""
from alembic import op
import sqlalchemy as sa

revision = "0014"
down_revision = "0013"
branch_labels = None
depends_on = None


def upgrade() -> None:
    with op.batch_alter_table("exams") as b:
        b.add_column(sa.Column("due_at", sa.DateTime(), nullable=True))
    with op.batch_alter_table("submissions") as b:
        b.add_column(sa.Column("submitted_at", sa.DateTime(), nullable=True))


def downgrade() -> None:
    with op.batch_alter_table("submissions") as b:
        b.drop_column("submitted_at")
    with op.batch_alter_table("exams") as b:
        b.drop_column("due_at")
