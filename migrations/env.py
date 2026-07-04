from logging.config import fileConfig

from alembic import context
from llm_observatory.db import database_url, get_engine
from llm_observatory.models import Base

config = context.config

if config.config_file_name is not None:
    fileConfig(config.config_file_name)

# Model metadata for 'autogenerate' support.
target_metadata = Base.metadata

# The URL comes from our app config (LLMOBS_DATABASE_URL env var, else sqlite default),
# so migrations target the same database the app uses — no hardcoded URL in alembic.ini.
URL = database_url()


def run_migrations_offline() -> None:
    context.configure(
        url=URL,
        target_metadata=target_metadata,
        literal_binds=True,
        dialect_opts={"paramstyle": "named"},
        render_as_batch=True,  # batch mode so SQLite can ALTER TABLE in later migrations
    )
    with context.begin_transaction():
        context.run_migrations()


def run_migrations_online() -> None:
    connectable = get_engine(URL)
    with connectable.connect() as connection:
        context.configure(
            connection=connection,
            target_metadata=target_metadata,
            render_as_batch=True,
        )
        with context.begin_transaction():
            context.run_migrations()


if context.is_offline_mode():
    run_migrations_offline()
else:
    run_migrations_online()
