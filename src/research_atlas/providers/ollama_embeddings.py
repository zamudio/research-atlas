"""Ollama batch embedding endpoint; only validated vectors leave the adapter."""

import httpx

from research_atlas.config import ProviderSettings
from research_atlas.embeddings import EmbeddingError, validate_vectors
from research_atlas.providers import ModelProviderError
from research_atlas.providers._config import model_base_url, model_credential, model_name
from research_atlas.providers._http import bearer_headers, post_json

_OLLAMA_EMBEDDING_BATCH_SIZE = 128


class OllamaEmbedder:
    def __init__(
        self, settings: ProviderSettings | None = None, client: httpx.AsyncClient | None = None
    ) -> None:
        settings = settings or ProviderSettings()
        # Reuse existing identity/URL/credential validation with independent embedding settings.
        embedding_settings = settings.model_copy(
            update={
                "model_name": settings.embedding_model_name,
                "model_base_url": settings.embedding_base_url,
            }
        )
        self._model = model_name(embedding_settings)
        self._key = model_credential(settings.ollama_api_key, "ollama", required=False)
        self._base_url = model_base_url(
            embedding_settings, "http://localhost:11434", api_key=self._key
        )
        self._timeout = settings.model_timeout_seconds
        self._client = client

    async def embed(self, texts: tuple[str, ...]) -> tuple[tuple[float, ...], ...]:
        if not texts or any(type(text) is not str or not text.strip() for text in texts):
            raise ValueError("embedding inputs must be nonblank text")
        vectors: list[tuple[float, ...]] = []
        for start in range(0, len(texts), _OLLAMA_EMBEDDING_BATCH_SIZE):
            batch = texts[start : start + _OLLAMA_EMBEDDING_BATCH_SIZE]
            try:
                envelope = await post_json(
                    self._client,
                    self._base_url + "/api/embed",
                    {"model": self._model, "input": list(batch), "truncate": True},
                    bearer_headers(self._key),
                    self._timeout,
                    "ollama_embedding",
                )
            except ModelProviderError as error:
                raise EmbeddingError(str(error)) from None
            identity = envelope.get("model")
            # Ollama may canonicalize an untagged local model to its :latest identity.
            if identity != self._model and not (
                ":" not in self._model and identity == self._model + ":latest"
            ):
                raise EmbeddingError("ollama_embedding_model_identity_mismatch")
            batch_vectors = validate_vectors(envelope.get("embeddings"), len(batch))
            if vectors and len(batch_vectors[0]) != len(vectors[0]):
                raise EmbeddingError("malformed_embedding_vectors")
            vectors.extend(batch_vectors)
        return validate_vectors(vectors, len(texts))
