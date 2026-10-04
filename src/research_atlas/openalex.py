"""Bounded, stateless OpenAlex search and scholarly content acquisition."""

import asyncio
from collections.abc import Awaitable, Callable
from datetime import UTC, datetime
from email.utils import parsedate_to_datetime
from ipaddress import ip_address
from threading import Lock
from time import monotonic

import httpx
from pydantic import BaseModel, ConfigDict, Field, SecretStr, ValidationError

from research_atlas.content import AcquiredContent, ContentKind, UnusableContent, prepare_content
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
    pdf_url: str | None = None
    is_oa: bool | None = False


class _HasContent(_WireModel):
    grobid_xml: bool = False
    pdf: bool = False


class _Work(_WireModel):
    id: str
    title: str | None = None
    doi: str | None = None
    publication_year: int | None = None
    authorships: list[_Authorship] | None = None
    primary_location: _Location | None = None
    best_oa_location: _Location | None = None
    locations: list[_Location] | None = None
    has_content: _HasContent | None = None
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

    async def fetch_content(self, source: Source) -> AcquiredContent | None:
        """Try each supported route until original content yields usable passages."""
        if self._key is None or not self._key.get_secret_value().strip():
            raise OpenAlexError("missing_api_key")
        raw_work = await self._get(
            f"https://api.openalex.org/works/{source.openalex_id}",
            params={"select": "id,has_content,best_oa_location,primary_location,locations"},
            bound=8 * 1024 * 1024,
            allow_missing=True,
        )
        if raw_work is None:
            return None
        try:
            work = _Work.model_validate_json(raw_work)
            if work.source().key != source.key:
                raise ValueError
        except ValidationError, ValueError:
            raise OpenAlexError("malformed_work_response") from None

        available = work.has_content or _HasContent()
        if available.grobid_xml:
            acquired = await self._cached_content(source, "grobid")
            if acquired is not None:
                return acquired

        urls: list[str] = []
        for location in (work.best_oa_location, work.primary_location, *(work.locations or ())):
            if location is None or not location.is_oa or not location.pdf_url:
                continue
            if location.pdf_url not in urls and _public_url(location.pdf_url):
                urls.append(location.pdf_url)
        for url in urls:
            acquired = _prepare(await self._external_pdf(url), "pdf")
            if acquired is not None:
                return acquired
        if available.pdf:
            return await self._cached_content(source, "pdf")
        return None

    async def _cached_content(self, source: Source, kind: ContentKind) -> AcquiredContent | None:
        extension = {"grobid": "grobid-xml", "pdf": "pdf"}[kind]
        try:
            raw = await self._get(
                f"https://content.openalex.org/works/{source.openalex_id}.{extension}",
                bound=MAX_CONTENT_BYTES,
                allow_missing=True,
            )
        except OpenAlexError as error:
            if not _content_miss(error):
                raise
            return None
        return _prepare(raw, kind)

    async def _external_pdf(self, url: str) -> bytes | None:
        if self._client is None:
            async with httpx.AsyncClient(timeout=_TIMEOUT) as client:
                return await OpenAlex(self._key, client)._external_pdf(url)
        try:
            # One total deadline and at most three redirects. Explicit Requests omit
            # client defaults (keys, cookies, auth) on every external hop.
            async with asyncio.timeout(_TIMEOUT):
                for hop in range(4):
                    if not _public_url(url):
                        return None
                    request = httpx.Request(
                        "GET",
                        url,
                        headers={"Accept": "application/pdf"},
                        extensions={
                            "timeout": dict.fromkeys(("connect", "read", "write", "pool"), _TIMEOUT)
                        },
                    )
                    response = await self._client.send(
                        request, stream=True, follow_redirects=False, auth=None
                    )
                    try:
                        if response.status_code in (301, 302, 303, 307, 308):
                            target = response.headers.get("Location")
                            if target is None or hop == 3:
                                return None
                            url = str(response.url.join(target))
                            continue
                        if response.status_code != 200:
                            return None
                        body = bytearray()
                        async for chunk in response.aiter_bytes():
                            if len(body) + len(chunk) > MAX_CONTENT_BYTES:
                                return None
                            body.extend(chunk)
                        return bytes(body)
                    finally:
                        await response.aclose()
        except httpx.HTTPError, httpx.InvalidURL, TimeoutError:
            return None
        return None

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
                        auth=None,
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


def _prepare(raw: bytes | None, kind: ContentKind) -> AcquiredContent | None:
    if raw is None:
        return None
    try:
        return prepare_content(raw, kind)
    except UnusableContent:
        return None


def _content_miss(error: OpenAlexError) -> bool:
    # Authentication/budget errors remain actionable system failures. A missing,
    # broken or oversized individual document can use the next route.
    return error.code in {
        "http_404",
        "http_410",
        "transport_failure",
        "content_size_exceeded",
        "empty_response",
        "invalid_response",
    } or error.code.startswith("http_5")


def _public_url(value: str) -> bool:
    try:
        url = httpx.URL(value)
    except httpx.InvalidURL:
        return False
    if url.scheme not in {"http", "https"} or not url.host or "%" in url.host or url.userinfo:
        return False
    if url.host.lower() == "localhost" or url.host.lower().endswith(".localhost"):
        return False
    try:
        return ip_address(url.host).is_global
    except ValueError:
        return True


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
