"""Parse only final Responses message text; completion policy stays in each adapter."""

from research_atlas.providers._http import (
    array_items,
    object_fields,
    text_bytes,
)


def response_text(fields: dict[str, object]) -> tuple[bytes | None, bool, bool]:
    texts: list[str] = []
    refused = False
    incomplete = False
    final_messages = 0
    for value in array_items(fields.get("output")):
        item = object_fields(value)
        if item.get("type") == "reasoning":
            continue
        if item.get("type") != "message" or item.get("role") != "assistant":
            raise ValueError
        phase = item.get("phase")
        if phase == "commentary":
            continue
        if phase is not None and phase != "final_answer":
            raise ValueError
        final_messages += 1
        if final_messages > 1:
            raise ValueError
        status = item.get("status")
        if status not in ("completed", "incomplete", "in_progress"):
            raise ValueError
        incomplete = status != "completed"
        for part in array_items(item.get("content")):
            segment = object_fields(part)
            if segment.get("type") == "refusal":
                refused = True
            elif segment.get("type") == "output_text":
                text = segment.get("text")
                if not isinstance(text, str):
                    raise ValueError
                texts.append(text)
            else:
                raise ValueError
    return text_bytes(texts), refused, incomplete
