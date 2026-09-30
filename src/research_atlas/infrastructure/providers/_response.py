"""Small wire-validation and opaque checkpoint helpers; no pagination orchestration."""

import hashlib
import json
from dataclasses import asdict

import httpx
from pydantic import BaseModel, ConfigDict, ValidationError

from research_atlas.application.ports.literature_source import (
    LiteratureQuery,
    LiteratureSourceError,
)


class WireModel(BaseModel):
    model_config = ConfigDict(strict=True, extra="ignore")


class Checkpoint(WireModel):
    request: str
    cursor: str
    offset: int


def malformed() -> LiteratureSourceError:
    return LiteratureSourceError(
        "provider returned malformed response", error_type="malformed_response"
    )


def parse_response[Model: BaseModel](response: httpx.Response, model: type[Model]) -> Model:
    try:
        return model.model_validate(response.json())
    except (ValueError, ValidationError) as error:
        raise malformed() from error


def _request_key(operation: str, query: LiteratureQuery) -> str:
    data = json.dumps([operation, asdict(query)], sort_keys=True).encode()
    return hashlib.sha256(data).hexdigest()


def read_checkpoint(token: str | None, operation: str, query: LiteratureQuery) -> tuple[str, int]:
    if token is None:
        return "*", 0
    try:
        value = Checkpoint.model_validate_json(token)
        if value.request != _request_key(operation, query) or not value.cursor or value.offset < 1:
            raise ValueError("invalid checkpoint")
        return value.cursor, value.offset
    except (ValueError, ValidationError) as error:
        raise LiteratureSourceError(
            "checkpoint does not match this search", error_type="invalid_checkpoint"
        ) from error


def next_checkpoint(cursor: str, offset: int, operation: str, query: LiteratureQuery) -> str:
    return Checkpoint(
        request=_request_key(operation, query), cursor=cursor, offset=offset
    ).model_dump_json()
