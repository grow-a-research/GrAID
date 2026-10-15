"""teacher/student accounts, server-side tokens, per-enrollment access codes

Existing classes keep teacher_id NULL until the first teacher registers and
adopts them. Existing enrollments are backfilled with unique access codes so
no current student is left without one. No existing submission data is touched.

Revision ID: 0013
Revises: 0012
Create Date: 2026-10-05
"""
import secrets

from alembic import op
import sqlalchemy as sa

revision = "0013"
down_revision = "0012"
branch_labels = None
depends_on = None

_ALPHABET = "ABCDEFGHJKLMNPQRSTUVWXYZ23456789"  # no 0/O/1/I


def _code() -> str:
    return "".join(secrets.choice(_ALPHABET) for _ in range(8))


def upgrade() -> None:
    op.create_table(
        "teachers",
        sa.Column("id", sa.Integer(), primary_key=True, autoincrement=True),
        sa.Column("email", sa.String(255), nullable=False),
        sa.Column("full_name", sa.String(255), nullable=False),
        sa.Column("password_hash", sa.String(255), nullable=False),
        sa.Column("created_at", sa.DateTime(), nullable=False),
    )
    op.create_index("ix_teachers_email", "teachers", ["email"], unique=True)

    op.create_table(
        "student_accounts",
        sa.Column("id", sa.Integer(), primary_key=True, autoincrement=True),
        sa.Column("email", sa.String(255), nullable=False),
        sa.Column("full_name", sa.String(255), nullable=False),
        sa.Column("password_hash", sa.String(255), nullable=False),
        sa.Column("student_id", sa.Integer(), sa.ForeignKey("students.id"), nullable=True, unique=True),
        sa.Column("created_at", sa.DateTime(), nullable=False),
    )
    op.create_index("ix_student_accounts_email", "student_accounts", ["email"], unique=True)

    op.create_table(
        "auth_tokens",
        sa.Column("id", sa.Integer(), primary_key=True, autoincrement=True),
        sa.Column("token_hash", sa.String(64), nullable=False),
        sa.Column("role", sa.String(16), nullable=False),
        sa.Column("user_id", sa.Integer(), nullable=False),
        sa.Column("created_at", sa.DateTime(), nullable=False),
        sa.Column("expires_at", sa.DateTime(), nullable=False),
    )
    op.create_index("ix_auth_tokens_token_hash", "auth_tokens", ["token_hash"], unique=True)
    op.create_index("ix_auth_tokens_user_id", "auth_tokens", ["user_id"])

    with op.batch_alter_table("course_classes") as b:
        b.add_column(sa.Column("teacher_id", sa.Integer(), nullable=True))
        b.create_foreign_key("fk_course_classes_teacher", "teachers", ["teacher_id"], ["id"])
        b.create_index("ix_course_classes_teacher_id", ["teacher_id"])

    with op.batch_alter_table("enrollments") as b:
        b.add_column(sa.Column("access_code", sa.String(16), nullable=True))
        b.add_column(sa.Column("redeemed_at", sa.DateTime(), nullable=True))
        b.create_index("ix_enrollments_access_code", ["access_code"], unique=True)

    with op.batch_alter_table("submissions") as b:
        b.add_column(sa.Column("uploaded_by", sa.String(16), nullable=True))

    conn = op.get_bind()
    used: set[str] = set()
    for (eid,) in conn.execute(sa.text("SELECT id FROM enrollments")).fetchall():
        code = _code()
        while code in used:
            code = _code()
        used.add(code)
        conn.execute(sa.text("UPDATE enrollments SET access_code = :c WHERE id = :i"), {"c": code, "i": eid})


def downgrade() -> None:
    with op.batch_alter_table("submissions") as b:
        b.drop_column("uploaded_by")
    with op.batch_alter_table("enrollments") as b:
        b.drop_index("ix_enrollments_access_code")
        b.drop_column("redeemed_at")
        b.drop_column("access_code")
    with op.batch_alter_table("course_classes") as b:
        b.drop_index("ix_course_classes_teacher_id")
        b.drop_constraint("fk_course_classes_teacher", type_="foreignkey")
        b.drop_column("teacher_id")
    op.drop_table("auth_tokens")
    op.drop_table("student_accounts")
    op.drop_table("teachers")
