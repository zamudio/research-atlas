"""OpenAlex cached XML acquisition; at most 32 MiB of transport-decoded bytes."""

import asyncio
from datetime import UTC, datetime
from typing import Literal
from xml.parsers.expat import ExpatError, ParserCreate

import httpx

from research_atlas.application.ports.document_acquisition import DocumentAcquisitionResult
from research_atlas.application.source_identity import openalex_work_id
from research_atlas.infrastructure.providers._http import Sleep, default_retry_delay

MAX_XML_BYTES = 32 * 1024 * 1024
_TIMEOUT_SECONDS = 20.0
_ATTEMPTS = 3


class OpenAlexDocumentAcquirer:
    """One Work, bearer authentication, three attempts, no redirects or PDF fallback."""

    provider_id = "openalex"

    def __init__(
        self,
        api_key: str | None = None,
        client: httpx.AsyncClient | None = None,
        *,
        retry_sleep: Sleep = asyncio.sleep,
    ) -> None:
        self._api_key = api_key
        self._client = client
        self._retry_sleep = retry_sleep

    async def acquire(self, provider_record_id: str) -> DocumentAcquisitionResult:
        work_id = openalex_work_id(provider_record_id)
        if work_id is None:
            raise ValueError("invalid OpenAlex acquisition identity")
        url = f"https://content.openalex.org/works/{work_id}.grobid-xml"
        if not self._api_key or not self._api_key.strip():
            return self._result(url, "failed", "missing_api_key")
        if self._client is not None:
            return await self._acquire(self._client, url)
        async with httpx.AsyncClient(timeout=_TIMEOUT_SECONDS) as client:
            return await self._acquire(client, url)

    @staticmethod
    def _result(
        url: str,
        status: Literal["usable", "unavailable", "failed", "incomplete"],
        outcome: str,
        content: bytes | None = None,
    ) -> DocumentAcquisitionResult:
        # All context comes from local constants/numeric HTTP status, never remote text.
        return DocumentAcquisitionResult(
            status=status,
            content_kind="grobid_xml",
            retrieval_context=f"openalex.grobid_xml; max_decoded_bytes={MAX_XML_BYTES}; {outcome}",
            retrieved_at=datetime.now(UTC),
            source_url=url,
            media_type="application/xml",
            content=content,
        )

    async def _acquire(self, client: httpx.AsyncClient, url: str) -> DocumentAcquisitionResult:
        for attempt in range(_ATTEMPTS):
            retry_after: str | None = None
            try:
                async with (
                    asyncio.timeout(_TIMEOUT_SECONDS),
                    client.stream(
                        "GET",
                        url,
                        headers={"Authorization": f"Bearer {self._api_key}"},
                        timeout=_TIMEOUT_SECONDS,
                        follow_redirects=False,
                    ) as response,
                ):
                    code = response.status_code
                    if code == 404:
                        return self._result(url, "unavailable", "http_status=404")
                    if code == 429 or 500 <= code <= 599:
                        if attempt + 1 == _ATTEMPTS:
                            return self._result(
                                url, "failed", f"http_status={code}; retries_exhausted"
                            )
                        retry_after = response.headers.get("Retry-After")
                    elif code != 200:
                        return self._result(url, "failed", f"http_status={code}")
                    else:
                        length = response.headers.get("Content-Length", "")
                        digits = length.lstrip("0")
                        encoding = response.headers.get("Content-Encoding", "").strip().lower()
                        if (
                            encoding in {"", "identity"}
                            and length.isascii()
                            and length.isdecimal()
                            and (len(digits) > 8 or int(digits or "0") > MAX_XML_BYTES)
                        ):
                            return self._result(url, "incomplete", "declared_size_exceeded")
                        body = bytearray()
                        async for chunk in response.aiter_bytes():
                            if len(body) + len(chunk) > MAX_XML_BYTES:
                                return self._result(url, "incomplete", "decoded_size_exceeded")
                            body.extend(chunk)
                        if not body:
                            return self._result(url, "failed", "empty_content")
                        content = bytes(body)
                        try:
                            # Expat validates without building/normalizing a TEI tree or
                            # fetching external entities. No particular root shape is required.
                            ParserCreate().Parse(content, True)
                        except ExpatError, ValueError, LookupError:
                            return self._result(url, "failed", "malformed_xml")
                        return self._result(url, "usable", "validated_xml", content)
            except httpx.TransportError, TimeoutError:
                if attempt + 1 == _ATTEMPTS:
                    return self._result(url, "failed", "transport_error; retries_exhausted")
            except httpx.DecodingError:
                return self._result(url, "failed", "content_decoding_error")
            # Reuse the metadata backoff policy, capping remote Retry-After to keep
            # this single acquisition bounded even if a provider supplies a huge delay.
            await self._retry_sleep(
                min(_TIMEOUT_SECONDS, default_retry_delay(retry_after, attempt))
            )
        raise RuntimeError("document acquisition retry loop ended unexpectedly")
