"""Alembic migration environment for custodex (E-04 — Postgres-first).

Reads the database URL from ``$CDMON_DATABASE_URL`` (default a local sqlite file for
dev) unless one is already set on the Alembic ``Config`` (the up/down test sets it
explicitly). ``target_metadata`` is ``db.Base.metadata`` — the SAME metadata
``create_all`` uses, so dev/test (``create_all``) and prod (these migrations) derive
from one source of truth and ``--autogenerate`` works.
"""

from __future__ import annotations

import os

from sqlalchemy import engine_from_config, pool

from alembic import context
from custodex.server.db import Base

config = context.config

# URL precedence: $CDMON_DATABASE_URL wins (prod / the `tests:pg` CI job); otherwise
# whatever `sqlalchemy.url` is on the Config — the up/down test sets it explicitly,
# and the alembic.ini default (a local sqlite file) is the dev fallback.
_env_url = os.environ.get("CDMON_DATABASE_URL")
if _env_url:
    config.set_main_option("sqlalchemy.url", _env_url)

target_metadata = Base.metadata


def run_migrations_offline() -> None:
    """Emit SQL to a script without a live DBAPI connection (``--sql``)."""
    url = config.get_main_option("sqlalchemy.url")
    context.configure(
        url=url,
        target_metadata=target_metadata,
        literal_binds=True,
        dialect_opts={"paramstyle": "named"},
        render_as_batch=True,
    )
    with context.begin_transaction():
        context.run_migrations()


def run_migrations_online() -> None:
    """Run migrations against a live connection (the normal path)."""
    connectable = engine_from_config(
        config.get_section(config.config_ini_section, {}),
        prefix="sqlalchemy.",
        poolclass=pool.NullPool,
    )
    with connectable.connect() as connection:
        # `render_as_batch` makes ALTERs work on SQLite (batch mode) so the same
        # migration scripts run on both SQLite (offline/tests) and Postgres.
        context.configure(
            connection=connection,
            target_metadata=target_metadata,
            render_as_batch=True,
        )
        with context.begin_transaction():
            context.run_migrations()


if context.is_offline_mode():  # pragma: no cover - the `--sql` offline leaf (K4)
    run_migrations_offline()
else:
    run_migrations_online()
