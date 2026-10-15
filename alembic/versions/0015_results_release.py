"""per-exam release of results to students

exams.results_released_at — when the teacher released this exam's results
(naive UTC). NULL = not released, so students see nothing about grades until a
teacher explicitly releases them. Every existing exam starts unreleased.

Revision ID: 0015
Revises: 0014
Create Date: 2026-10-11
"""
from alembic import op
import sqlalchemy as sa

revision = "0015"
down_revision = "0014"
branch_labels = None
depends_on = None


def upgrade() -> None:
    with op.batch_alter_table("exams") as b:
        b.add_column(sa.Column("results_released_at", sa.DateTime(), nullable=True))


def downgrade() -> None:
    with op.batch_alter_table("exams") as b:
        b.drop_column("results_released_at")
