import io
from dataclasses import replace
from datetime import timedelta
from hashlib import sha256
from types import MappingProxyType
from uuid import uuid7

import pytest
from alembic import command
from alembic.config import Config
from sqlalchemy.dialects import postgresql
from sqlalchemy.schema import CreateTable

from research_atlas.application.ports.literature_source import LiteratureBatch
from research_atlas.infrastructure.persistence.database import (
    DatabaseSettings,
    create_database_engine,
    database_url,
)
from research_atlas.infrastructure.persistence.evidence import verify_content
from research_atlas.infrastructure.persistence.identity import incoming_components
from research_atlas.infrastructure.persistence.schema import metadata
from research_atlas.infrastructure.persistence.serialization import (
    batch_digest,
    batch_key,
    canonical_bytes,
)
from tests.persistence.helpers import observation


def test_batch_digest_ignores_provisional_identity_and_retrieval_time_but_not_reports() -> None:
    record = observation()
    provenance = record.source.provider_provenance[0]
    assert provenance.retrieved_at is not None
    repeated = replace(
        record,
        observation_id=uuid7(),
        source=replace(
            record.source,
            source_id=uuid7(),
            provider_provenance=(
                replace(provenance, retrieved_at=provenance.retrieved_at + timedelta(days=1)),
            ),
        ),
    )
    first = LiteratureBatch((record,), "next", False)
    assert batch_digest(first) == batch_digest(replace(first, records=(repeated,)))
    assert batch_digest(first) != batch_digest(
        replace(first, records=(replace(record, source=replace(record.source, title="Changed")),))
    )
    assert batch_digest(first) != batch_digest(replace(first, next_checkpoint="different"))
    assert batch_key(None) != batch_key("initial")


def test_serialization_preserves_order_rejects_nan_and_naive_times() -> None:
    assert canonical_bytes({"b": [2, 1], "a": 0}) == b'{"a":0,"b":[2,1]}'
    assert canonical_bytes(MappingProxyType({"values": [2, 1]})) == b'{"values":[2,1]}'
    with pytest.raises(ValueError):
        canonical_bytes(float("nan"))
    stamp = observation().source.provider_provenance[0].retrieved_at
    assert stamp is not None
    with pytest.raises(ValueError, match="timezone"):
        canonical_bytes(stamp.replace(tzinfo=None))


def test_checksum_verification_and_keyless_components() -> None:
    verify_content(b"exact", sha256(b"exact").hexdigest(), usable=True)
    with pytest.raises(ValueError, match="checksum"):
        verify_content(b"different", sha256(b"exact").hexdigest(), usable=True)
    with pytest.raises(ValueError, match="retained"):
        verify_content(None, None, usable=True)
    records = (
        observation(None, None),
        observation(None, None),
        observation("W1"),
        observation("W2"),
    )
    assert sorted(incoming_components(records)) == [[0], [1], [2, 3]]


def test_configuration_is_explicit_secret_and_psycopg_only(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.delenv("RESEARCH_ATLAS_DATABASE_URL", raising=False)
    with pytest.raises(ValueError, match="DATABASE_URL"):
        create_database_engine()
    url = "postgresql+psycopg://user:secret@localhost/atlas"
    monkeypatch.setenv("RESEARCH_ATLAS_DATABASE_URL", url)
    assert "secret" not in repr(DatabaseSettings())
    assert database_url(url) == url
    with pytest.raises(ValueError, match="psycopg"):
        database_url("sqlite://")


def test_frozen_migration_renders_all_fourteen_postgresql_relations_without_connecting(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("RESEARCH_ATLAS_TEST_DATABASE_URL", "postgresql+psycopg://unused/unused")
    output = io.StringIO()
    config = Config("alembic.ini", output_buffer=output)
    command.upgrade(config, "head", sql=True)
    sql = output.getvalue()
    assert len(metadata.tables) == 14
    assert (
        sql.count("CREATE TABLE ") == 15
    )  # Fourteen application tables plus Alembic's version row.
    for table in metadata.tables.values():
        assert f"CREATE TABLE {table.name} (" in sql
        assert "CASCADE" not in str(CreateTable(table).compile(dialect=postgresql.dialect()))
    assert "CREATE TRIGGER immutable_findings" in sql
    assert "fk_sources_display_observation" in sql
