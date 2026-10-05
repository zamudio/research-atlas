import asyncio
import json
from typing import cast

import httpx
import pytest
from pydantic import SecretStr

from research_atlas.config import ProviderSettings
from research_atlas.embeddings import Embedder, EmbeddingError, rank_texts
from research_atlas.providers.factory import create_embedder
from research_atlas.providers.ollama_embeddings import OllamaEmbedder


class FakeEmbedder:
    def __init__(self, vectors: tuple[tuple[float, ...], ...]) -> None:
        self.vectors = vectors
        self.calls: list[tuple[str, ...]] = []

    async def embed(self, texts: tuple[str, ...]) -> tuple[tuple[float, ...], ...]:
        self.calls.append(texts)
        return self.vectors


def test_cosine_ranking_stable_ties_and_exact_inputs() -> None:
    embedder = FakeEmbedder(((1, 0), (0, 1), (1, 1), (4, 0), (2, 2), (-1, 0)))
    texts = ("irrelevant", "relevant", "best", "tied", "opposite")
    assert asyncio.run(rank_texts(" question\n", texts, embedder)) == (2, 1, 3, 0, 4)
    assert embedder.calls == [(" question\n", *texts)]
    assert asyncio.run(rank_texts("question", (), embedder)) == ()
    assert len(embedder.calls) == 1


def test_cosine_handles_extreme_finite_values() -> None:
    embedder = FakeEmbedder(((1e308, 1e308), (1e-308, 1e-308), (1e308, -1e308)))
    assert asyncio.run(rank_texts("q", ("aligned", "orthogonal"), embedder)) == (0, 1)


@pytest.mark.parametrize(
    "vectors",
    [
        None,
        {},
        "vectors",
        [],
        [[1, 0]],
        [[1, 0]] * 3,
        [[1, 0], []],
        [[1, 0], [1]],
        [[1, 0], [0, 0]],
        [[1, 0], ["1", 0]],
        [[1, 0], [True, 0]],
        [[1, 0], [None, 0]],
        [[1, 0], [float("nan"), 0]],
        [[1, 0], [float("inf"), 0]],
        [[1, 0], [10**1000, 0]],
    ],
)
def test_malformed_fake_vectors_fail_before_ranking(vectors: object) -> None:
    embedder = FakeEmbedder(cast(tuple[tuple[float, ...], ...], vectors))
    with pytest.raises(EmbeddingError, match="malformed_embedding_vectors"):
        asyncio.run(rank_texts("q", ("text",), embedder))


@pytest.mark.parametrize("identity", ["nomic-embed-text", "nomic-embed-text:latest"])
def test_ollama_embedding_request_contract(identity: str) -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        assert str(request.url) == "http://localhost:11434/api/embed"
        assert "Authorization" not in request.headers
        assert json.loads(request.content) == {
            "model": "nomic-embed-text",
            "input": [" question\n", "Exact passage."],
            "truncate": True,
        }
        assert request.extensions["timeout"] == dict.fromkeys(
            ("connect", "read", "write", "pool"), 600
        )
        return httpx.Response(200, json={"model": identity, "embeddings": [[1, 0], [0.5, 1]]})

    async def scenario() -> None:
        async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as client:
            embedder = OllamaEmbedder(ProviderSettings(), client)
            assert await embedder.embed((" question\n", "Exact passage.")) == ((1, 0), (0.5, 1))

    asyncio.run(scenario())


@pytest.mark.parametrize(
    "count,batch_sizes", [(128, [128]), (129, [128, 1]), (385, [128, 128, 128, 1])]
)
def test_ollama_embedding_batches_are_sequential_and_preserve_order(
    count: int, batch_sizes: list[int]
) -> None:
    texts = tuple(f" passage {index}\n" for index in range(count))
    calls: list[list[str]] = []
    in_flight = False

    async def handler(request: httpx.Request) -> httpx.Response:
        nonlocal in_flight
        assert not in_flight
        in_flight = True
        await asyncio.sleep(0)
        start = sum(len(batch) for batch in calls)
        batch = list(texts[start : start + batch_sizes[len(calls)]])
        assert str(request.url) == "http://localhost:11434/api/embed"
        assert "Authorization" not in request.headers
        assert json.loads(request.content) == {
            "model": "nomic-embed-text",
            "input": batch,
            "truncate": True,
        }
        assert request.extensions["timeout"] == dict.fromkeys(
            ("connect", "read", "write", "pool"), 600
        )
        calls.append(batch)
        in_flight = False
        return httpx.Response(
            200,
            json={
                "model": "nomic-embed-text:latest" if len(calls) % 2 else "nomic-embed-text",
                "embeddings": [[index + 1, -index] for index in range(start, start + len(batch))],
            },
        )

    async def scenario() -> None:
        async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as client:
            assert await OllamaEmbedder(client=client).embed(texts) == tuple(
                (index + 1, -index) for index in range(count)
            )

    asyncio.run(scenario())
    assert [len(batch) for batch in calls] == batch_sizes
    assert tuple(text for batch in calls for text in batch) == texts


@pytest.mark.parametrize(
    "body",
    [
        b"not json",
        b"[]",
        b"{}",
        b'{"model":"wrong","embeddings":[[1],[1]]}',
        b'{"model":"all-minilm:other","embeddings":[[1],[1]]}',
        b'{"model":"all-minilm","embeddings":[[1]]}',
        b'{"model":"all-minilm","embeddings":[[1],["credential"]]}',
        b'{"model":"all-minilm","embeddings":[[1],[true]]}',
        b'{"model":"all-minilm","embeddings":[[1],[0]]}',
        b'{"model":"all-minilm","embeddings":[[1],[1,2]]}',
        b'{"model":"all-minilm","embeddings":[[1],[NaN]]}',
    ],
)
def test_ollama_embedding_malformed_envelopes_are_safe(body: bytes) -> None:
    async def scenario() -> None:
        async with httpx.AsyncClient(
            transport=httpx.MockTransport(lambda _: httpx.Response(200, content=body))
        ) as client:
            with pytest.raises(EmbeddingError) as error:
                await OllamaEmbedder(
                    ProviderSettings(embedding_model_name="all-minilm"), client
                ).embed(("q", "text"))
            assert "credential" not in str(error.value)
            assert error.value.__cause__ is None

    asyncio.run(scenario())


@pytest.mark.parametrize("fault", ["http", "redirect", "transport", "timeout"])
@pytest.mark.parametrize("failed_batch", [1, 2])
def test_ollama_embedding_provider_failures_are_safe(fault: str, failed_batch: int) -> None:
    calls = 0

    def handler(request: httpx.Request) -> httpx.Response:
        nonlocal calls
        calls += 1
        assert request.headers["Authorization"] == "Bearer private-key"
        if calls < failed_batch:
            return httpx.Response(
                200, json={"model": "nomic-embed-text:latest", "embeddings": [[1]] * 128}
            )
        if fault == "transport":
            raise httpx.ConnectError("credential private-key private-input", request=request)
        if fault == "timeout":
            raise httpx.ReadTimeout("credential private-key private-input", request=request)
        return httpx.Response(
            302 if fault == "redirect" else 503, text="credential private-key private-input"
        )

    async def scenario() -> None:
        async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as client:
            with pytest.raises(EmbeddingError) as error:
                await OllamaEmbedder(
                    ProviderSettings(ollama_api_key=SecretStr("private-key")), client
                ).embed(("private-input",) * 257)
            assert str(error.value) == (
                "ollama_embedding_http_failure"
                if fault in ("http", "redirect")
                else "ollama_embedding_transport_failure"
            )
            assert error.value.__cause__ is None

    asyncio.run(scenario())
    assert calls == failed_batch


@pytest.mark.parametrize(
    "body,code",
    [
        (b"credential private-key private-input", "ollama_embedding_malformed_envelope"),
        (b"[]", "ollama_embedding_malformed_envelope"),
        (b"{}", "ollama_embedding_model_identity_mismatch"),
        (
            json.dumps({"model": "nomic-embed-text:other", "embeddings": [[1]] * 128}).encode(),
            "ollama_embedding_model_identity_mismatch",
        ),
        (
            json.dumps({"model": "nomic-embed-text", "embeddings": [[1]]}).encode(),
            "malformed_embedding_vectors",
        ),
        (
            json.dumps(
                {"model": "nomic-embed-text", "embeddings": [[1]] * 127 + [["private-key"]]}
            ).encode(),
            "malformed_embedding_vectors",
        ),
        (
            json.dumps({"model": "nomic-embed-text", "embeddings": [[1, 2]] * 128}).encode(),
            "malformed_embedding_vectors",
        ),
    ],
)
def test_ollama_embedding_bad_later_batch_stops_safely(body: bytes, code: str) -> None:
    calls = 0

    def handler(_: httpx.Request) -> httpx.Response:
        nonlocal calls
        calls += 1
        if calls == 1:
            return httpx.Response(
                200, json={"model": "nomic-embed-text:latest", "embeddings": [[1]] * 128}
            )
        return httpx.Response(200, content=body)

    async def scenario() -> None:
        async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as client:
            with pytest.raises(EmbeddingError) as error:
                await OllamaEmbedder(
                    ProviderSettings(ollama_api_key=SecretStr("private-key")), client
                ).embed(("private-input",) * 257)
            assert str(error.value) == code
            assert error.value.__cause__ is None

    asyncio.run(scenario())
    assert calls == 2


def test_embedding_factory_and_environment_are_independent(monkeypatch: pytest.MonkeyPatch) -> None:
    assert ProviderSettings().embedding_model_name == "nomic-embed-text"
    assert create_embedder(ProviderSettings()) is None
    monkeypatch.setenv("RESEARCH_ATLAS_EMBEDDING_PROVIDER", "ollama")
    monkeypatch.setenv("RESEARCH_ATLAS_EMBEDDING_MODEL_NAME", "all-minilm:latest")
    monkeypatch.setenv("RESEARCH_ATLAS_EMBEDDING_BASE_URL", "https://embedding.test")
    chosen = ProviderSettings(model_provider="openai", model_name="structured")
    assert chosen.embedding_model_name == "all-minilm:latest"
    embedder: Embedder | None = create_embedder(chosen)
    assert isinstance(embedder, OllamaEmbedder)
    with pytest.raises(ValueError, match="embedding provider"):
        create_embedder(ProviderSettings(embedding_provider="openai"))


def test_embedding_endpoint_key_and_explicit_identity() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        assert str(request.url) == "https://embedding.test/api/embed"
        assert request.headers["Authorization"] == "Bearer private-key"
        assert json.loads(request.content)["model"] == "all-minilm:v2"
        return httpx.Response(200, json={"model": "all-minilm:v2", "embeddings": [[1]]})

    async def scenario() -> None:
        async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as client:
            embedder = create_embedder(
                ProviderSettings(
                    embedding_provider="ollama",
                    embedding_model_name="all-minilm:v2",
                    embedding_base_url="https://embedding.test",
                    model_base_url="https://unused.test",
                    ollama_api_key=SecretStr("private-key"),
                ),
                client,
            )
            assert embedder is not None
            assert await embedder.embed(("text",)) == ((1,),)
            assert "private-key" not in repr(embedder)

    asyncio.run(scenario())


@pytest.mark.parametrize("identity", ["", " ", "x" * 201, "all-minilm\n"])
def test_invalid_embedding_identity(identity: str) -> None:
    with pytest.raises(ValueError):
        OllamaEmbedder(ProviderSettings(embedding_model_name=identity))


@pytest.mark.parametrize("url", ["ftp://host", "https://user:secret@host", "https://host?key=x"])
def test_invalid_embedding_url(url: str) -> None:
    with pytest.raises(ValueError):
        OllamaEmbedder(ProviderSettings(embedding_base_url=url))


def test_embedding_credentials_require_secure_remote_endpoint() -> None:
    with pytest.raises(ValueError, match="requires HTTPS") as error:
        OllamaEmbedder(
            ProviderSettings(
                embedding_base_url="http://remote.test", ollama_api_key=SecretStr("private-key")
            )
        )
    assert "private-key" not in str(error.value)


@pytest.mark.parametrize(
    "texts", [(), (" ",), ("q", ""), ("q", None), ("q", 1), ("q",) * 128 + (" ",)]
)
def test_embedding_input_validation_precedes_io(texts: tuple[object, ...]) -> None:
    def handler(_: httpx.Request) -> httpx.Response:
        pytest.fail("invalid inputs must fail before any HTTP request")

    async def scenario() -> None:
        async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as client:
            with pytest.raises(ValueError, match="nonblank"):
                await OllamaEmbedder(client=client).embed(cast(tuple[str, ...], texts))

    asyncio.run(scenario())
