"""Stateless batch embeddings and stable cosine ranking, separate from generation."""

from collections.abc import Sequence
from math import fsum, isfinite, sqrt
from typing import Protocol, cast


class EmbeddingError(Exception):
    """Safe failure code without provider bodies, credentials, or input text."""


class Embedder(Protocol):
    async def embed(self, texts: tuple[str, ...]) -> tuple[tuple[float, ...], ...]: ...


def validate_vectors(value: object, count: int) -> tuple[tuple[float, ...], ...]:
    """Reject count/dimension mismatches, nonfinite/non-numeric values and zero vectors."""
    try:
        if not isinstance(value, (list, tuple)):
            raise ValueError
        items = cast(Sequence[object], value)
        if len(items) != count:
            raise ValueError
        vectors: list[tuple[float, ...]] = []
        dimension: int | None = None
        for item in items:
            if not isinstance(item, (list, tuple)) or not item:
                raise ValueError
            numbers: list[float] = []
            for number in cast(Sequence[object], item):
                if type(number) not in (int, float):
                    raise ValueError
                numeric = float(cast(int | float, number))
                if not isfinite(numeric):
                    raise ValueError
                numbers.append(numeric)
            vector = tuple(numbers)
            if not any(vector) or (dimension is not None and len(vector) != dimension):
                raise ValueError
            dimension = len(vector)
            vectors.append(vector)
        return tuple(vectors)
    except ValueError, OverflowError:
        raise EmbeddingError("malformed_embedding_vectors") from None


def _unit(vector: tuple[float, ...]) -> tuple[float, ...]:
    # Scaling first avoids overflow/underflow even for finite extreme magnitudes.
    scale = max(abs(value) for value in vector)
    scaled = tuple(value / scale for value in vector)
    norm = sqrt(fsum(value * value for value in scaled))
    return tuple(value / norm for value in scaled)


async def rank_texts(question: str, texts: tuple[str, ...], embedder: Embedder) -> tuple[int, ...]:
    """Return candidate positions by descending cosine; ties retain input order."""
    if not texts:
        return ()
    vectors = validate_vectors(await embedder.embed((question, *texts)), len(texts) + 1)
    query = _unit(vectors[0])
    scores = [
        fsum(a * b for a, b in zip(query, _unit(vector), strict=True)) for vector in vectors[1:]
    ]
    return tuple(sorted(range(len(texts)), key=lambda position: -scores[position]))
