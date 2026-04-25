import logging
from logging.config import fileConfig

from alembic import context

# this is the Alembic Config object, which provides
# access to the values within the .ini file in use.
config = context.config

# Interpret the config file for Python logging.
if config.config_file_name is not None:
    fileConfig(config.config_file_name)

target_metadata = None

def run_migrations_offline() -> None:
    context.configure(
        url=config.get_main_option("sqlalchemy.url"),
        target_metadata=target_metadata,
        literal_binds=True,
        dialect_opts={"paramstyle": "named"},
    )
    with context.begin_transaction():
        context.run_migrations()

def run_migrations_online() -> None:
    # Instead of an engine, we accept the raw sqlite3.Connection passed in by
    # caden.libbie.db.apply_schema -> config.attributes.
    # However we need SQLAlchemy to do dialects for Alembic
    connectable = config.attributes.get('connection', None)
    if connectable is None:
        raise Exception("No connection provided to alembic through attributes")
        
    context.configure(
        connection=connectable,
        target_metadata=target_metadata,
        render_as_batch=True,
    )
    with context.begin_transaction():
        context.run_migrations()

if context.is_offline_mode():
    run_migrations_offline()
else:
    run_migrations_online()
