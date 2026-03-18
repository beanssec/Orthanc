import asyncio
from logging.config import fileConfig

from sqlalchemy import pool
from sqlalchemy.engine import Connection
from sqlalchemy.ext.asyncio import async_engine_from_config

from alembic import context

# Pull in all models so autogenerate can see them
from app.models.base import Base  # noqa: F401
import app.models.user  # noqa: F401
import app.models.credential  # noqa: F401
import app.models.post  # noqa: F401
import app.models.source  # noqa: F401
import app.models.event  # noqa: F401
import app.models.alert  # noqa: F401

from app.config import settings

config = context.config

# Override sqlalchemy.url from settings
config.set_main_option("sqlalchemy.url", settings.DATABASE_URL)

if config.config_file_name is not None:
    fileConfig(config.config_file_name)

target_metadata = Base.metadata


def run_migrations_offline() -> None:
    url = config.get_main_option("sqlalchemy.url")
    context.configure(
        url=url,
        target_metadata=target_metadata,
        literal_binds=True,
        dialect_opts={"paramstyle": "named"},
    )
    with context.begin_transaction():
        context.run_migrations()


def do_run_migrations(connection: Connection) -> None:
    context.configure(connection=connection, target_metadata=target_metadata)

    # Log current and target revisions before applying migrations (TASK-53)
    import logging as _logging
    _mig_log = _logging.getLogger("alembic.migration_safety")
    try:
        from alembic.runtime.migration import MigrationContext as _MC
        _mc = _MC.configure(connection)
        _current = _mc.get_current_revision()
        _heads = context.get_head_revisions() if hasattr(context, "get_head_revisions") else ("head",)
        _mig_log.info(
            "Migration safety check | current_revision=%s target=%s",
            _current or "<none>",
            _heads,
        )
    except Exception as _e:
        _mig_log.warning("Could not determine current revision: %s", _e)

    with context.begin_transaction():
        context.run_migrations()


async def run_async_migrations() -> None:
    connectable = async_engine_from_config(
        config.get_section(config.config_ini_section, {}),
        prefix="sqlalchemy.",
        poolclass=pool.NullPool,
    )
    async with connectable.connect() as connection:
        await connection.run_sync(do_run_migrations)
    await connectable.dispose()


def run_migrations_online() -> None:
    asyncio.run(run_async_migrations())


if context.is_offline_mode():
    run_migrations_offline()
else:
    run_migrations_online()
