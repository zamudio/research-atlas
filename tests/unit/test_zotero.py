from collections.abc import Iterable, Mapping
from typing import Any

from research_workbench.infrastructure.providers.zotero import ZoteroReferenceLibrary


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
                "creators": [{"firstName": "Dana", "lastName": "Scholar"}],
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
    assert record.authors == ("Dana Scholar",)
    assert record.year == 2020
    assert record.source_type == "journalarticle"
    assert {(item.namespace, item.value) for item in record.external_identifiers} >= {
        ("doi", "10.1000/zotero"),
        ("pmid", "12345"),
        ("arxiv", "2001.00001"),
        ("zotero", "ITEM1"),
    }


def test_zotero_ignores_notes_and_attachments() -> None:
    library = ZoteroReferenceLibrary(FakeZotero(_items()))

    assert library.get_source("NOTE1") is None
    assert library.get_source("ATT1") is None
    assert [record.title for record in library.list_collection("COLL1")] == ["A Zotero paper"]
