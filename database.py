import os
from collections.abc import Generator
from pathlib import Path

from sqlalchemy import create_engine, inspect, text
from sqlalchemy.orm import DeclarativeBase, Session, sessionmaker

DATABASE_URL = os.getenv("DATABASE_URL", "sqlite:///./data/app.db")

_PROJECT_ROOT = Path(__file__).resolve().parent


class Base(DeclarativeBase):
    pass


connect_args = {"check_same_thread": False} if DATABASE_URL.startswith("sqlite") else {}
engine = create_engine(DATABASE_URL, connect_args=connect_args)
SessionLocal = sessionmaker(autocommit=False, autoflush=False, bind=engine)


def get_db() -> Generator[Session, None, None]:
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()


def init_db() -> None:
    """
    Initialise the database using Alembic migrations.

    Handles three startup scenarios:

    1. Fresh DB (no tables)  → run all migrations from scratch (0001 → head).
    2. Pre-Alembic DB        → tables exist but no alembic_version table.
                               Stamp at 0001 (initial schema already in place),
                               then upgrade to head (applies 0002 onward).
    3. Already migrated DB   → alembic_version present, upgrade is a no-op or
                               applies only new migrations.
    """
    print("[DB] Initialising database...")

    # Ensure the data directory exists before SQLite tries to open the file.
    ((_PROJECT_ROOT / "data")).mkdir(parents=True, exist_ok=True)

    # Import models so they register with Base.metadata (needed by env.py too).
    import db_models  # noqa: F401

    from alembic import command
    from alembic.config import Config

    cfg = Config(str(_PROJECT_ROOT / "alembic.ini"))

    insp = inspect(engine)
    tables_exist = insp.has_table("course_classes")
    version_table_exists = insp.has_table("alembic_version")

    if tables_exist and not version_table_exists:
        print("[DB] Pre-Alembic database detected — stamping at 0001...")
        command.stamp(cfg, "0001")

    # Apply any unapplied migrations (no-op when already at head).
    print("[DB] Running migrations...")
    command.upgrade(cfg, "head")
    print("[DB] Database ready.")
