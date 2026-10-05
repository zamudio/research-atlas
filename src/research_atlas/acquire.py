"""Try advertised routes in order, accepting only content that can be prepared."""

import asyncio
from ipaddress import ip_address

import httpx

from research_atlas.config import Settings
from research_atlas.models import ContentSource, Document, Failure, Work
from research_atlas.prepare import MAX_DOCUMENT_BYTES, prepare


def public_url(value: str) -> bool:
    try:
        url = httpx.URL(value)
    except httpx.InvalidURL:
        return False
    if url.scheme not in {"http", "https"} or not url.host or "%" in url.host or url.userinfo:
        return False
    if url.host == "localhost" or url.host.endswith(".localhost"):
        return False
    try:
        return ip_address(url.host).is_global
    except ValueError:
        return True


async def _download(
    source: ContentSource, client: httpx.AsyncClient, settings: Settings
) -> tuple[bytes, str]:
    url = httpx.URL(source.url)
    async with asyncio.timeout(settings.http_timeout_seconds):
        for hop in range(4):
            if not public_url(str(url)):
                raise ValueError("unsupported content URL")
            headers = {
                "Accept": "application/xml" if source.kind == "grobid_xml" else "application/pdf"
            }
            if (
                source.kind != "oa_pdf"
                and url.scheme == "https"
                and url.host == "content.openalex.org"
            ):
                headers["Authorization"] = f"Bearer {settings.openalex_api_key.get_secret_value()}"
            # Explicit requests keep client cookies/default credentials out of OA requests.
            request = httpx.Request(
                "GET",
                url,
                headers=headers,
                extensions={"timeout": httpx.Timeout(settings.http_timeout_seconds).as_dict()},
            )
            response = await client.send(request, stream=True, follow_redirects=False, auth=None)
            try:
                if response.is_redirect and "location" in response.headers and hop < 3:
                    url = response.url.join(response.headers["location"])
                    continue
                response.raise_for_status()
                content = bytearray()
                async for chunk in response.aiter_bytes():
                    if len(content) + len(chunk) > MAX_DOCUMENT_BYTES:
                        raise ValueError("content exceeds 32 MiB")
                    content.extend(chunk)
                return bytes(content), str(response.url)
            finally:
                await response.aclose()
    raise ValueError("too many content redirects")


async def acquire(work: Work, client: httpx.AsyncClient, settings: Settings) -> Document | Failure:
    preparation_failed = False
    for source in work.routes:
        try:
            content, url = await _download(source, client, settings)
        except httpx.HTTPError, httpx.InvalidURL, TimeoutError, ValueError:
            continue
        try:
            return prepare(work, ContentSource(kind=source.kind, url=url), content)
        except ValueError:
            preparation_failed = True
    return Failure(
        openalex_id=work.openalex_id,
        stage="preparation" if preparation_failed else "acquisition",
        reason=(
            "No downloaded full text could be prepared; all advertised routes were exhausted."
            if preparation_failed
            else "No advertised full-text route succeeded."
        ),
    )
