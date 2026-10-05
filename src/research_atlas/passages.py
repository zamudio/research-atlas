"""Temporary passage labels over exact prepared GROBID blocks; no text splitting."""

from collections.abc import Awaitable, Callable, Mapping
from dataclasses import dataclass
from types import MappingProxyType

from research_atlas.embeddings import Embedder, rank_texts
from research_atlas.providers import ModelProviderError

MAX_PASSAGE_CHARACTERS = 20_000
PASSAGE_EMBEDDING_CHARACTERS = 4_000


@dataclass(frozen=True, slots=True)
class PassageIndex:
    passages: Mapping[str, str]

    @property
    def model_text(self) -> str:
        return "\n\n".join(f"[{key}] {text}" for key, text in self.passages.items()) + "\n"

    def resolve(self, passage_id: str) -> str:
        try:
            return self.passages[passage_id]
        except KeyError:
            raise ValueError("unknown evidence passage ID") from None


def build_passage_index(content: bytes) -> PassageIndex:
    """Index prepared UTF-8 bytes, preserving block text exactly.

    The projection joins blocks with two newlines and appends one terminal newline.
    Reject oversized blocks rather than truncate or chunk the supporting evidence.
    """
    passages: dict[str, str] = {}
    for block in content.decode("utf-8").removesuffix("\n").split("\n\n"):
        if not block.strip():
            continue
        if len(block) > MAX_PASSAGE_CHARACTERS:
            raise ValueError("prepared block exceeds passage bound")
        passages[f"p{len(passages) + 1:04d}"] = block
    if not passages:
        raise ValueError("prepared document has no nonblank passages")
    return PassageIndex(MappingProxyType(passages))


async def select_context(
    index: PassageIndex,
    question: str,
    embedder: Embedder | None,
    fits_context: Callable[[str], Awaitable[bool]],
) -> PassageIndex:
    """Reduce only requests that exceed the generation model's context capacity."""
    if await fits_context(index.model_text):
        return index
    if embedder is None:
        raise ModelProviderError("context_reduction_requires_embedder")
    passages = tuple(index.passages.items())
    order = await rank_texts(
        question, tuple(text[:PASSAGE_EMBEDDING_CHARACTERS] for _, text in passages), embedder
    )
    selected: set[int] = set()

    def view(positions: set[int]) -> PassageIndex:
        return PassageIndex(
            MappingProxyType(
                {key: text for i, (key, text) in enumerate(passages) if i in positions}
            )
        )

    for hit in order:
        if hit not in selected:
            if not await fits_context(view(selected | {hit}).model_text):
                continue
            selected.add(hit)
        for position in (hit - 1, hit + 1):
            if not 0 <= position < len(passages) or position in selected:
                continue
            if await fits_context(view(selected | {position}).model_text):
                selected.add(position)
    if not selected:
        raise ModelProviderError("context_capacity_cannot_fit_passage")
    return view(selected)
