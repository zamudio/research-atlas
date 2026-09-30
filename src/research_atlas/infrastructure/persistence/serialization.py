"""Canonical validated payloads; never hash provisional UUIDs or retrieval timestamps."""

import json
from collections.abc import Mapping
from dataclasses import fields, is_dataclass
from datetime import UTC, datetime
from hashlib import sha256
from typing import Any, cast
from uuid import UUID

from research_atlas.application.ports.literature_source import LiteratureBatch, LiteratureRecord


def _json_default(value: object) -> object:
    if isinstance(value, UUID):
        return str(value)
    if isinstance(value, datetime):
        if value.tzinfo is None or value.utcoffset() is None:
            raise ValueError("durable timestamps must be timezone-aware")
        return value.astimezone(UTC).isoformat()
    if is_dataclass(value) and not isinstance(value, type):
        return {field.name: getattr(value, field.name) for field in fields(value)}
    if isinstance(value, Mapping):
        return dict(cast(Mapping[str, object], value))
    raise TypeError(f"unsupported persistence value: {type(value).__name__}")


def canonical_bytes(value: object) -> bytes:
    return json.dumps(
        value,
        default=_json_default,
        sort_keys=True,
        separators=(",", ":"),
        ensure_ascii=False,
        allow_nan=False,
    ).encode("utf-8")


def json_value(value: object) -> Any:
    """Convert trusted structured data to JSON primitives, rejecting unsupported values/NaN."""
    return json.loads(canonical_bytes(value))


def digest(value: object) -> str:
    return sha256(canonical_bytes(value)).hexdigest()


def batch_key(checkpoint: str | None) -> str:
    return "initial" if checkpoint is None else "cursor:" + checkpoint


def reported_content(record: LiteratureRecord) -> dict[str, Any]:
    source = record.source
    return json_value(
        {
            "title": source.title,
            "credits": record.credits,
            "year": source.year,
            "source_type": source.source_type,
            "source_url": source.source_url,
            "identifiers": source.external_identifiers,
        }
    )


def batch_digest(batch: LiteratureBatch) -> str:
    return digest(
        {
            "records": [
                {
                    "provider": record.source.provider_provenance[0].provider.strip().lower(),
                    "provider_record_id": (
                        record.source.provider_provenance[0].provider_record_id or ""
                    ).strip()
                    or None,
                    "reported": reported_content(record),
                }
                for record in batch.records
            ],
            "next_checkpoint": batch.next_checkpoint,
            "exhausted": batch.exhausted,
            "start_position": batch.start_position,
        }
    )
