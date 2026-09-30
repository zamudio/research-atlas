"""One conventional migration environment sharing the Core schema metadata."""

import os

from alembic import context
from sqlalchemy import create_engine, pool

from research_atlas.infrastructure.persistence.database import configured_database_url, database_url
from research_atlas.infrastructure.persistence.schema import metadata

target_metadata = metadata


def run_migrations() -> None:
    supplied_connection = context.config.attributes.get("connection")
    if supplied_connection is not None:
        context.configure(
            connection=supplied_connection, target_metadata=target_metadata, compare_type=True
        )
        with context.begin_transaction():
            context.run_migrations()
        return
    # Explicit test URL takes precedence so test/CI migrations never use runtime credentials.
    url = database_url(
        os.environ.get("RESEARCH_ATLAS_TEST_DATABASE_URL") or configured_database_url()
    )
    if context.is_offline_mode():
        context.configure(url=url, target_metadata=target_metadata, literal_binds=True)
        with context.begin_transaction():
            context.run_migrations()
        return
    engine = create_engine(url, poolclass=pool.NullPool)
    try:
        with engine.connect() as connection:
            context.configure(
                connection=connection, target_metadata=target_metadata, compare_type=True
            )
            with context.begin_transaction():
                context.run_migrations()
    finally:
        engine.dispose()


run_migrations()
