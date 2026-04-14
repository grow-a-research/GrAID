import os
import sys
from logging.config import fileConfig
from pathlib import Path

from alembic import context
from sqlalchemy import engine_from_config, pool

# Make the project root importable so database.py / db_models.py can be found.
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from database import Base, DATABASE_URL  # noqa: E402
import db_models  # noqa: F401, E402 — registers all ORM classes with Base.metadata

config = context.config

# Only apply Alembic's logging config when running from the CLI (alembic upgrade head).
# When called programmatically from database.init_db(), skip it — otherwise fileConfig()
# overwrites uvicorn's log setup and suppresses INFO messages like
# "Application startup complete."
if config.config_file_name is not None and context.is_offline_mode():
    fileConfig(config.config_file_name)

target_metadata = Base.metadata


def get_url() -> str:
    """Prefer DATABASE_URL env var; fall back to alembic.ini value."""
    return os.getenv("DATABASE_URL", config.get_main_option("sqlalchemy.url", ""))


def run_migrations_offline() -> None:
    context.configure(
        url=get_url(),
        target_metadata=target_metadata,
        literal_binds=True,
        dialect_opts={"paramstyle": "named"},
    )
    with context.begin_transaction():
        context.run_migrations()


def run_migrations_online() -> None:
    from database import engine

    with engine.connect() as connection:
        context.configure(connection=connection, target_metadata=target_metadata)
        with context.begin_transaction():
            context.run_migrations()


if context.is_offline_mode():
    run_migrations_offline()
else:
    run_migrations_online()
