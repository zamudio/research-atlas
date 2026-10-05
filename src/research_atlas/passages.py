"""Temporary passage labels over exact prepared GROBID blocks; no text splitting."""

from collections.abc import Mapping
from dataclasses import dataclass
from types import MappingProxyType

from research_atlas.embeddings import Embedder, rank_texts

MAX_PASSAGE_CHARACTERS = 20_000
PAPER_CONTEXT_CHARACTERS = 60_000
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
    index: PassageIndex, question: str, embedder: Embedder | None
) -> PassageIndex:
    """Reduce large papers with a configured embedder; propagate embedding failures."""
    if embedder is None or len(index.model_text) <= PAPER_CONTEXT_CHARACTERS:
        return index
    passages = tuple(index.passages.items())
    order = await rank_texts(
        question, tuple(text[:PASSAGE_EMBEDDING_CHARACTERS] for _, text in passages), embedder
    )
    selected: set[int] = set()
    # Each entry costs its ID, text, and two separating newlines; the last costs one less.
    used = -1
    for hit in order:
        if hit not in selected:
            key, text = passages[hit]
            cost = len(key) + len(text) + 5
            if used + cost > PAPER_CONTEXT_CHARACTERS:
                continue
            selected.add(hit)
            used += cost
        for position in (hit - 1, hit + 1):
            if not 0 <= position < len(passages) or position in selected:
                continue
            key, text = passages[position]
            cost = len(key) + len(text) + 5
            if used + cost <= PAPER_CONTEXT_CHARACTERS:
                selected.add(position)
                used += cost
    return PassageIndex(
        MappingProxyType({key: text for i, (key, text) in enumerate(passages) if i in selected})
    )
