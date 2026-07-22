"""Alembic environment. Lấy URL từ settings (hoặc env DATABASE_URL) và metadata từ adapter."""
from __future__ import annotations

from alembic import context
from sqlalchemy import engine_from_config, pool

from legalguard.adapters.outbound.sql_case_repository import Base, normalize_crdb_url
from legalguard.config.settings import settings

# URL CRDB tự chuẩn hóa sang cockroachdb+psycopg:// (vanilla postgres dialect không parse nổi CRDB).
_DB_URL = normalize_crdb_url(settings.database_url)

config = context.config
config.set_main_option("sqlalchemy.url", _DB_URL)

target_metadata = Base.metadata


def run_migrations_offline() -> None:
    context.configure(url=_DB_URL, target_metadata=target_metadata,
                      literal_binds=True, render_as_batch=True)
    with context.begin_transaction():
        context.run_migrations()


def run_migrations_online() -> None:
    connectable = engine_from_config(
        config.get_section(config.config_ini_section, {}),
        prefix="sqlalchemy.", poolclass=pool.NullPool,
    )
    with connectable.connect() as connection:
        # render_as_batch: cần cho ALTER trên SQLite.
        context.configure(connection=connection, target_metadata=target_metadata,
                          render_as_batch=True)
        with context.begin_transaction():
            context.run_migrations()


if context.is_offline_mode():
    run_migrations_offline()
else:
    run_migrations_online()
