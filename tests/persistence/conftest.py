"""No explicit test URL means no connection or mutation, even if a runtime URL exists."""

import asyncio
import os
import sys
from collections.abc import Coroutine, Iterator
from typing import Any
from uuid import uuid4

import pytest
import sqlalchemy as sa
from alembic import command
from alembic.config import Config
from sqlalchemy.ext.asyncio import AsyncEngine, create_async_engine
from sqlalchemy.pool import NullPool

from research_atlas.infrastructure.persistence.database import database_url


def run[T](coroutine: Coroutine[Any, Any, T]) -> T:
    # Psycopg cannot use Windows Proactor loops. No global production policy mutation.
    with asyncio.Runner(
        loop_factory=asyncio.SelectorEventLoop if sys.platform == "win32" else None
    ) as runner:
        return runner.run(coroutine)


@pytest.fixture
def pg_engine() -> Iterator[AsyncEngine]:
    url = os.environ.get("RESEARCH_ATLAS_TEST_DATABASE_URL")
    if not url:
        pytest.skip("PostgreSQL acceptance requires RESEARCH_ATLAS_TEST_DATABASE_URL")
    database_url(url)
    schema = "atlas_test_" + uuid4().hex
    admin = sa.create_engine(url, poolclass=NullPool)
    with admin.begin() as conn:
        conn.execute(sa.text(f'CREATE SCHEMA "{schema}"'))
    scoped_url = sa.engine.make_url(url).update_query_dict({"options": f"-csearch_path={schema}"})
    migrations = sa.create_engine(scoped_url, poolclass=NullPool)
    engine = create_async_engine(scoped_url, poolclass=NullPool)
    try:
        with migrations.begin() as conn:
            config = Config("alembic.ini")
            config.attributes["connection"] = conn
            command.upgrade(config, "head")
        yield engine
    finally:
        run(engine.dispose())
        migrations.dispose()
        with admin.begin() as conn:
            # Generated per-test schema only; never truncate developer or runtime tables.
            conn.execute(sa.text(f'DROP SCHEMA "{schema}" CASCADE'))
        admin.dispose()
