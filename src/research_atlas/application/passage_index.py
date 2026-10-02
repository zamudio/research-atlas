"""Versioned passage labels over exact prepared GROBID blocks; no text splitting."""

from collections.abc import Mapping
from dataclasses import dataclass
from types import MappingProxyType

PASSAGE_INDEX_VERSION = "atlas.passage-index.v1"
MAX_PASSAGE_CHARACTERS = 20_000


@dataclass(frozen=True, slots=True)
class PassageIndex:
    version: str
    passages: Mapping[str, str]

    @property
    def model_text(self) -> str:
        return "\n\n".join(f"[{key}] {text}" for key, text in self.passages.items()) + "\n"

    def resolve(self, passage_id: str) -> str:
        try:
            return self.passages[passage_id]
        except KeyError:
            raise ValueError("unknown evidence passage ID") from None


def build_passage_index(content: bytes, *, version: str = PASSAGE_INDEX_VERSION) -> PassageIndex:
    """Reconstruct v1 from immutable grobid_text bytes, preserving block text exactly.

    Projection v1 joins blocks with two newlines and appends one terminal newline.
    Reject oversized blocks rather than truncate or chunk the supporting evidence.
    """
    if version != PASSAGE_INDEX_VERSION:
        raise ValueError("unsupported passage-index version")
    passages: dict[str, str] = {}
    for block in content.decode("utf-8").removesuffix("\n").split("\n\n"):
        if not block.strip():
            continue
        if len(block) > MAX_PASSAGE_CHARACTERS:
            raise ValueError("prepared block exceeds passage bound")
        passages[f"p{len(passages) + 1:04d}"] = block
    if not passages:
        raise ValueError("prepared document has no nonblank passages")
    return PassageIndex(version, MappingProxyType(passages))
