"""Bounded, stateless OpenAlex search and cached GROBID XML acquisition."""

import asyncio
from collections.abc import Awaitable, Callable
from datetime import UTC, datetime
from email.utils import parsedate_to_datetime
from threading import Lock
from time import monotonic

import httpx
from pydantic import BaseModel, ConfigDict, Field, SecretStr, ValidationError

from research_atlas.embeddings import Embedder, rank_texts
from research_atlas.models import Source

MAX_CONTENT_BYTES = 32 * 1024 * 1024
LEXICAL_CANDIDATE_POOL = 50
_TIMEOUT = 20.0
_semantic_lock = Lock()
_last_semantic_start = 0.0


class OpenAlexError(Exception):
    """Safe local error code without provider responses or request credentials."""

    def __init__(self, code: str) -> None:
        self.code = code
        super().__init__(code)


class _WireModel(BaseModel):
    model_config = ConfigDict(strict=True, extra="ignore")


class _Author(_WireModel):
    display_name: str | None = None


class _Authorship(_WireModel):
    raw_author_name: str | None = None
    author: _Author | None = None


class _Location(_WireModel):
    landing_page_url: str | None = None


class _Work(_WireModel):
    id: str
    title: str | None = None
    doi: str | None = None
    publication_year: int | None = None
    authorships: list[_Authorship] | None = None
    primary_location: _Location | None = None
    abstract_inverted_index: dict[str, list[int]] | None = None

    def source(self) -> Source:
        return Source(
            title=self.title or "",
            authors=tuple(
                (credit.raw_author_name or "").strip()
                or ((credit.author.display_name or "").strip() if credit.author else "")
                for credit in self.authorships or ()
            ),
            year=self.publication_year,
            doi=self.doi,
            openalex_id=self.id,
            url=self.primary_location.landing_page_url if self.primary_location else None,
        )

    def ranking_text(self) -> str:
        words: dict[int, str] = {}
        for word, positions in (self.abstract_inverted_index or {}).items():
            for position in positions:
                if position < 0 or position in words or not word.strip():
                    raise ValueError("invalid abstract positions")
                words[position] = word
        abstract = " ".join(words[position] for position in sorted(words))
        return "\n\n".join(part for part in (self.title or "", abstract) if part)


class _Results(_WireModel):
    results: list[_Work] = Field(max_length=200)


def _retry_delay(value: str | None, attempt: int) -> float:
    try:
        delay = float(value) if value is not None else 0.5 * 2**attempt
    except ValueError:
        try:
            date = parsedate_to_datetime(value or "")
            if date.tzinfo is None:
                date = date.replace(tzinfo=UTC)
            delay = (date - datetime.now(UTC)).total_seconds()
        except ValueError, TypeError, OverflowError:
            delay = 0.5 * 2**attempt
    return min(_TIMEOUT, max(0.0, delay))


class OpenAlex:
    def __init__(
        self,
        api_key: SecretStr | None = None,
        client: httpx.AsyncClient | None = None,
        *,
        retry_sleep: Callable[[float], Awaitable[None]] = asyncio.sleep,
    ) -> None:
        self._key = api_key
        self._client = client
        self._sleep = retry_sleep

    async def search(
        self,
        query: str,
        *,
        limit: int = 20,
        semantic: bool = False,
        embedder: Embedder | None = None,
    ) -> tuple[Source, ...]:
        """Use provider order, or local reranking after semantic provider failure."""
        maximum = 50 if semantic else 200
        if type(query) is not str or not query.strip() or len(query) > 2000:
            raise ValueError("search query must be nonblank and at most 2000 characters")
        if type(limit) is not int or not 1 <= limit <= maximum:
            raise ValueError(f"search limit must be between 1 and {maximum}")
        try:
            works = await self._search_works(query, limit=limit, semantic=semantic)
        except OpenAlexError:
            # Only the provider/request boundary can trigger fallback; validation is above.
            if not semantic or embedder is None:
                raise
            works = await self._search_works(
                query, limit=LEXICAL_CANDIDATE_POOL, semantic=False, abstracts=True
            )
            try:
                texts = tuple(work.ranking_text() for work in works)
            except ValueError:
                raise OpenAlexError("malformed_search_response") from None
            order = await rank_texts(query, texts, embedder)
            works = tuple(works[position] for position in order[:limit])
        return tuple(work.source() for work in works)

    async def _search_works(
        self, query: str, *, limit: int, semantic: bool, abstracts: bool = False
    ) -> tuple[_Work, ...]:
        raw = await self._get(
            "https://api.openalex.org/works",
            params={
                "search.semantic" if semantic else "search": query,
                "per_page": limit,
                "select": "id,title,doi,publication_year,authorships,primary_location"
                + (",abstract_inverted_index" if abstracts else ""),
            },
            bound=8 * 1024 * 1024,
            semantic=semantic,
        )
        try:
            results = _Results.model_validate_json(raw or b"")
            if len(results.results) > limit:
                raise ValueError
            # Check canonical identity before any ranking; richer work data stays private.
            for work in results.results:
                work.source()
            return tuple(results.results)
        except ValidationError, ValueError:
            raise OpenAlexError("malformed_search_response") from None

    async def fetch_content(self, source: Source) -> bytes | None:
        """Return bounded cached GROBID XML bytes; None means OpenAlex returned 404."""
        if self._key is None or not self._key.get_secret_value().strip():
            raise OpenAlexError("missing_api_key")
        return await self._get(
            f"https://content.openalex.org/works/{source.openalex_id}.grobid-xml",
            bound=MAX_CONTENT_BYTES,
            allow_missing=True,
        )

    async def _get(
        self,
        url: str,
        *,
        bound: int,
        params: dict[str, str | int] | None = None,
        allow_missing: bool = False,
        semantic: bool = False,
    ) -> bytes | None:
        if self._client is None:
            async with httpx.AsyncClient(timeout=_TIMEOUT) as client:
                return await OpenAlex(self._key, client, retry_sleep=self._sleep)._get(
                    url, bound=bound, params=params, allow_missing=allow_missing, semantic=semantic
                )
        headers = {"Authorization": f"Bearer {self._key.get_secret_value()}"} if self._key else {}
        for attempt in range(3):
            retry_after = None
            if semantic:
                await _pace_semantic()
            try:
                async with (
                    asyncio.timeout(_TIMEOUT),
                    self._client.stream(
                        "GET",
                        url,
                        params=params,
                        headers=headers,
                        timeout=_TIMEOUT,
                        follow_redirects=False,
                    ) as response,
                ):
                    code = response.status_code
                    if allow_missing and code == 404:
                        return None
                    if code == 429 or 500 <= code <= 599:
                        if attempt == 2:
                            raise OpenAlexError(f"http_{code}")
                        retry_after = response.headers.get("Retry-After")
                    elif code != 200:
                        raise OpenAlexError(f"http_{code}")
                    else:
                        body = bytearray()
                        async for chunk in response.aiter_bytes():
                            if len(body) + len(chunk) > bound:
                                raise OpenAlexError("content_size_exceeded")
                            body.extend(chunk)
                        if not body:
                            raise OpenAlexError("empty_response")
                        return bytes(body)
            except httpx.TransportError, TimeoutError:
                if attempt == 2:
                    raise OpenAlexError("transport_failure") from None
            except httpx.HTTPError:
                raise OpenAlexError("invalid_response") from None
            await self._sleep(_retry_delay(retry_after, attempt))
        raise AssertionError("unreachable")


async def _pace_semantic() -> None:
    """Space semantic request starts across clients, including transient retries."""
    global _last_semantic_start
    while True:
        with _semantic_lock:
            now = monotonic()
            delay = _last_semantic_start + 1.1 - now
            if delay <= 0:
                _last_semantic_start = now
                return
        await asyncio.sleep(delay)
