from __future__ import annotations

from kover.bulk_write_builder import BulkWriteBuilder
from kover.models.collation import Collation
from kover.models.operations import Delete, Update


def test_bulk_write_build_preserves_namespace_order_and_options() -> None:
    builder = BulkWriteBuilder(
        ordered=False,
        bypass_document_validation=True,
        comment="batch-1",
        let={"tenant": "north"},
        errors_only=True,
        cursor_batch_size=17,
        write_concern=2,
    )
    document = {"_id": 1}
    builder.add_insert([document], ns="shop.items")
    builder.add_insert([{"_id": 2}], ns="shop.items")
    builder.add_update(
        Update(
            {"_id": 1},
            {"$set": {"name": "new"}},
            upsert=True,
            collation=Collation(locale="en"),
        ),
        "shop.items",
    )
    builder.add_delete(Delete({"_id": 2}, limit=1), "shop.archive")

    command = builder.build()
    assert command == {
        "bulkWrite": 1,
        "ops": [
            {"insert": 0, "document": document},
            {"insert": 0, "document": {"_id": 2}},
            {
                "update": 0,
                "filter": {"_id": 1},
                "updateMods": {"$set": {"name": "new"}},
                "constants": None,
                "upsert": True,
                "multi": False,
                "collation": Collation(locale="en").model_dump(),
            },
            {
                "delete": 1,
                "filter": {"_id": 2},
                "multi": False,
            },
        ],
        "nsInfo": [{"ns": "shop.items"}, {"ns": "shop.archive"}],
        "ordered": False,
        "bypassDocumentValidation": True,
        "comment": "batch-1",
        "let": {"tenant": "north"},
        "errorsOnly": True,
        "cursor": {"batchSize": 17},
        "writeConcern": {"w": 2},
    }
    assert document == {"_id": 1}


def test_bulk_write_defaults_empty_build_and_zero_batch_size() -> None:
    builder = BulkWriteBuilder(cursor_batch_size=0)
    assert builder.build() == {
        "bulkWrite": 1,
        "ops": [],
        "nsInfo": [],
        "ordered": True,
        "bypassDocumentValidation": False,
        "errorsOnly": False,
        "cursor": {"batchSize": 101},
        "writeConcern": {"w": "majority"},
    }
