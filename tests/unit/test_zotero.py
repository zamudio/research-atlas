from collections.abc import Iterable, Mapping
from typing import Any

from research_atlas.infrastructure.providers.zotero import ZoteroReferenceLibrary


class FakeZotero:
    def __init__(self, items: list[Mapping[str, Any]]) -> None:
        self.items = items

    def item(self, item_key: str) -> Mapping[str, Any]:
        return next(item for item in self.items if item["key"] == item_key)

    def collection_items(self, collection_id: str) -> Iterable[Mapping[str, Any]]:
        assert collection_id == "COLL1"
        return self.items


def _items() -> list[Mapping[str, Any]]:
    return [
        {
            "key": "ITEM1",
            "data": {
                "key": "ITEM1",
                "itemType": "journalArticle",
                "title": "A Zotero paper",
                "creators": [
                    {
                        "creatorType": "author",
                        "firstName": "Dana",
                        "lastName": "Scholar",
                    },
                    {"creatorType": "editor", "name": "Study Group"},
                    {
                        "creatorType": "translator",
                        "firstName": "Terry",
                        "lastName": "Translator",
                    },
                ],
                "date": "2020-06-01",
                "DOI": "doi:10.1000/ZOTERO",
                "url": "https://example.test/zotero",
                "extra": "PMID: 12345\narXiv: 2001.00001v3",
            },
        },
        {"key": "NOTE1", "data": {"key": "NOTE1", "itemType": "note"}},
        {"key": "ATT1", "data": {"key": "ATT1", "itemType": "attachment"}},
    ]


def test_zotero_maps_bibliographic_item() -> None:
    library = ZoteroReferenceLibrary(FakeZotero(_items()))

    record = library.get_source("ITEM1")

    assert record is not None
    assert record.title == "A Zotero paper"
    assert record.authors == ("Dana Scholar", "Study Group", "Terry Translator")
    assert record.year == 2020
    assert record.source_type == "journalarticle"
    assert {(item.namespace, item.value) for item in record.external_identifiers} >= {
        ("doi", "10.1000/zotero"),
        ("pmid", "12345"),
        ("arxiv", "2001.00001"),
        ("zotero", "ITEM1"),
    }

    structured = library.get_literature_record("ITEM1")
    assert structured is not None
    assert structured.source.title == record.title
    assert [item.display_name for item in structured.contribution_observations] == [
        "Dana Scholar",
        "Study Group",
        "Terry Translator",
    ]
    assert [item.role for item in structured.contribution_observations] == [
        "author",
        "editor",
        "translator",
    ]
    assert [item.provider_position for item in structured.contribution_observations] == [1, 2, 3]
    assert [item.provider_record_id for item in structured.contribution_observations] == [
        None,
        None,
        None,
    ]
    assert [item.observed_contributor_kind for item in structured.contribution_observations] == [
        "person",
        "unknown",
        "person",
    ]
    assert all(item.provider == "zotero" for item in structured.contribution_observations)
    assert all(
        item.retrieved_at == structured.source.provider_provenance[0].retrieved_at
        for item in structured.contribution_observations
    )


def test_zotero_ignores_notes_and_attachments() -> None:
    library = ZoteroReferenceLibrary(FakeZotero(_items()))

    assert library.get_source("NOTE1") is None
    assert library.get_source("ATT1") is None
    assert [record.title for record in library.list_collection("COLL1")] == ["A Zotero paper"]
