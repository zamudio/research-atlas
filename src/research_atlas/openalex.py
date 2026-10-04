"""Bounded, stateless OpenAlex search and scholarly content acquisition."""

import asyncio
import re
from collections.abc import Awaitable, Callable
from dataclasses import dataclass
from datetime import UTC, datetime
from email.utils import parsedate_to_datetime
from ipaddress import ip_address
from threading import Lock
from time import monotonic

import httpx
from pydantic import BaseModel, ConfigDict, SecretStr, TypeAdapter, ValidationError

from research_atlas.content import AcquiredContent, ContentKind, UnusableContent, prepare_content
from research_atlas.embeddings import Embedder, EmbeddingError, rank_texts
from research_atlas.models import Source

MAX_CONTENT_BYTES = 32 * 1024 * 1024
DEFAULT_ELIGIBLE_POOL_TARGET = 50
DISCOVERY_POOL_SIZE = 100
NATIVE_SEMANTIC_LIMIT = 50
_TIMEOUT = 20.0
_semantic_lock = Lock()
_last_semantic_start = 0.0
_ABSTRACT_INDEX = TypeAdapter(dict[str, list[int]])


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


@dataclass(frozen=True, slots=True)
class ContentCandidate:
    """Internal discovery result with supported acquisition routes and ranking input."""

    source: Source
    grobid_xml: bool
    pdf_urls: tuple[str, ...]
    pdf: bool
    ranking_text: str = ""


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
    # Ranking-only data stays unvalidated until an eligible work needs ranking text.
    abstract_inverted_index: object = None

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
        abstract_index = (
            _ABSTRACT_INDEX.validate_python(self.abstract_inverted_index, strict=True)
            if self.abstract_inverted_index is not None
            else {}
        )
        words: dict[int, str] = {}
        for word, positions in abstract_index.items():
            for position in positions:
                if position < 0 or position in words or not word.strip():
                    raise ValueError("invalid abstract positions")
                words[position] = word
        abstract = " ".join(words[position] for position in sorted(words))
        return "\n\n".join(part for part in (self.title or "", abstract) if part)

    def candidate(self, *, abstracts: bool) -> ContentCandidate | None:
        source = self.source()  # Validate canonical identity even for ineligible works.
        available = self.has_content or _HasContent()
        urls: list[str] = []
        for location in (self.best_oa_location, self.primary_location, *(self.locations or ())):
            if location is None or not location.is_oa or not location.pdf_url:
                continue
            if location.pdf_url not in urls and _public_url(location.pdf_url):
                urls.append(location.pdf_url)
        if not (available.grobid_xml or urls or available.pdf):
            return None
        return ContentCandidate(
            source,
            available.grobid_xml,
            tuple(urls),
            available.pdf,
            self.ranking_text() if abstracts else "",
        )


class _Results(_WireModel):
    results: list[_Work]


def _lexical_query(query: str) -> str:
    """Treat human text as lexical terms, neutralizing OpenAlex query syntax."""
    query = query.translate(
        str.maketrans({char: " " for char in '*?~"\u201c\u201d\u201e\u201f()!|\\'})
    )
    query = re.sub(r"\b(?:AND|OR|NOT)\b", lambda match: match[0].lower(), query)
    query = " ".join(query.split())
    if not query:
        raise ValueError("lexical search query must be nonblank after normalization")
    return query


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
    ) -> tuple[ContentCandidate, ...]:
        """Use limit as the eligible lexical pool target, with optional local ranking.

        Native semantic search remains an independent provider-ranked path.
        """
        maximum = NATIVE_SEMANTIC_LIMIT if semantic else DISCOVERY_POOL_SIZE
        if type(query) is not str or not query.strip() or len(query) > 2000:
            raise ValueError("search query must be nonblank and at most 2000 characters")
        if type(limit) is not int or not 1 <= limit <= maximum:
            raise ValueError(f"search limit must be between 1 and {maximum}")
        if not semantic:
            candidates = await self._search_candidates(
                query,
                limit=limit,
                semantic=False,
                abstracts=embedder is not None,
            )
            if embedder is not None:
                try:
                    order = await rank_texts(
                        query, tuple(candidate.ranking_text for candidate in candidates), embedder
                    )
                except EmbeddingError:
                    pass  # Recoverable embedding failures retain eligible lexical order.
                else:
                    candidates = tuple(candidates[position] for position in order)
            return candidates
        try:
            candidates = await self._search_candidates(query, limit=limit, semantic=semantic)
        except OpenAlexError:
            # Only the provider/request boundary can trigger fallback; validation is above.
            if not semantic or embedder is None:
                raise
            candidates = await self._search_candidates(
                query,
                limit=max(DEFAULT_ELIGIBLE_POOL_TARGET, limit),
                semantic=False,
                abstracts=True,
            )
            texts = tuple(candidate.ranking_text for candidate in candidates)
            order = await rank_texts(query, texts, embedder)
            candidates = tuple(candidates[position] for position in order[:limit])
        return candidates

    async def _search_candidates(
        self, query: str, *, limit: int, semantic: bool, abstracts: bool = False
    ) -> tuple[ContentCandidate, ...]:
        # One discovery response supplies citation, eligibility and ranking data.
        per_page = limit if semantic else DISCOVERY_POOL_SIZE
        if not semantic:
            query = _lexical_query(query)
        raw = await self._get(
            "https://api.openalex.org/works",
            params={
                "search.semantic" if semantic else "search": query,
                "per_page": per_page,
                "select": "id,title,doi,publication_year,authorships,primary_location"
                + ",has_content,best_oa_location,locations"
                + (",abstract_inverted_index" if abstracts else ""),
            },
            bound=8 * 1024 * 1024,
            semantic=semantic,
        )
        candidates: list[ContentCandidate] = []
        try:
            results = _Results.model_validate_json(raw or b"")
            if len(results.results) > per_page:
                raise ValueError
            for work in results.results:
                candidate = work.candidate(abstracts=abstracts)
                if candidate is not None:
                    candidates.append(candidate)
                    if len(candidates) == limit:
                        break
        except ValidationError, ValueError:
            raise OpenAlexError("malformed_search_response") from None
        return tuple(candidates)

    async def fetch_content(self, candidate: ContentCandidate) -> AcquiredContent | None:
        """Try only discovery-advertised routes, without another Work lookup."""
        if self._key is None or not self._key.get_secret_value().strip():
            raise OpenAlexError("missing_api_key")
        if candidate.grobid_xml:
            acquired = await self._cached_content(candidate.source, "grobid")
            if acquired is not None:
                return acquired

        for url in candidate.pdf_urls:
            acquired = _prepare(await self._external_pdf(url), "pdf")
            if acquired is not None:
                return acquired
        if candidate.pdf:
            return await self._cached_content(candidate.source, "pdf")
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
