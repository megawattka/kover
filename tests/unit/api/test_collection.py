from __future__ import annotations

from unittest.mock import AsyncMock, MagicMock

from elune import ObjectId
import pytest

from kover.collection import Collection
from kover.models.collation import Collation
from kover.models.concerns import ReadConcern, WriteConcern
from kover.models.indexes import Index, IndexDirection
from kover.models.operations import Delete, Update
from kover.schema.document import Document


def make_collection() -> tuple[Collection, AsyncMock]:
    database = MagicMock()
    database.name = "shop"
    database.command = AsyncMock(return_value={"ok": 1})
    database.drop_collection = AsyncMock()
    database.list_collections = AsyncMock(return_value=[])
    collection = Collection("items", database)
    return collection, database.command


async def test_insert_operations_generate_ids_without_mutating_input() -> None:
    collection, command = make_collection()
    source = {"name": "one"}
    document_id = await collection.insert_one(source, comment="one")
    assert isinstance(document_id, ObjectId)
    assert source == {"name": "one"}
    assert command.await_args is not None
    assert command.await_args.args[0] == {
        "insert": "items",
        "ordered": True,
        "documents": [{"name": "one", "_id": document_id}],
        "maxTimeMS": 0,
        "bypassDocumentValidation": False,
        "comment": "one",
    }

    existing_id = ObjectId()
    docs = [{"_id": existing_id, "name": "two"}, {"name": "three"}]
    ids = await collection.insert_many(docs, ordered=False, comment="many")
    assert ids[0] == existing_id
    assert isinstance(ids[1], ObjectId)
    assert "_id" not in docs[1]
    assert command.await_args.args[0]["ordered"] is False
    assert command.await_args.args[0]["comment"] == "many"
    assert command.await_args.args[0]["documents"][0]["_id"] == existing_id


async def test_update_delete_clear_serialize_requests_and_results() -> None:
    collection, command = make_collection()
    command.return_value = {"nModified": 3}
    update = Update({"active": True}, {"$set": {"active": False}}, upsert=True)
    assert await collection.update(update, let={"scope": "users"}) == 3
    assert command.await_args is not None
    assert command.await_args.args[0] == {
        "update": "items",
        "updates": [update.model_dump()],
        "ordered": True,
        "maxTimeMS": 0,
        "bypassDocumentValidation": False,
        "let": {"scope": "users"},
    }

    command.return_value = {"n": 2}
    delete = Delete({"expired": True}, limit=0)
    assert (
        await collection.delete(
            delete,
            write_concern=WriteConcern(w=1, j=True),
            comment="cleanup",
        )
        == 2
    )
    assert command.await_args.args[0] == {
        "delete": "items",
        "deletes": [delete.model_dump()],
        "comment": "cleanup",
        "ordered": True,
        "writeConcern": {"w": 1, "j": True},
        "maxTimeMS": 0,
    }

    command.return_value = {"n": 9}
    assert await collection.clear() == 9
    assert command.await_args.args[0]["deletes"] == [
        Delete({}, limit=0).model_dump(),
    ]


async def test_query_commands_and_aggregation_options() -> None:
    collection, command = make_collection()
    command.return_value = {"n": 4}
    concern = ReadConcern(level="majority")
    collation = Collation(locale="en", case_level=True)
    assert (
        await collection.count(
            {"active": True},
            limit=10,
            skip=2,
            hint="active_1",
            collation=collation,
            read_concern=concern,
            comment="count",
        )
        == 4
    )
    assert command.await_args is not None
    assert command.await_args.args[0] == {
        "count": "items",
        "query": {"active": True},
        "limit": 10,
        "maxTimeMS": 0,
        "readConcern": concern.model_dump(),
        "skip": 2,
        "hint": "active_1",
        "collation": collation.model_dump(),
        "comment": "count",
    }

    command.return_value = {"values": ["a", "b"]}
    assert await collection.distinct("name", {"active": True}) == ["a", "b"]
    assert command.await_args.args[0] == {
        "distinct": "items",
        "key": "name",
        "query": {"active": True},
    }

    cursor = collection.aggregate(
        [{"$match": {"active": True}}],
        explain=True,
        cursor={"batchSize": 4},
        collation=collation,
        read_concern=concern,
        hint="active_1",
        write_concern=WriteConcern(w=2),
        let={"x": 1},
    )
    assert cursor._query == {  # ruff: ignore[private-member-access] # pyright: ignore[reportPrivateUsage]
        "aggregate": "items",
        "pipeline": [{"$match": {"active": True}}],
        "cursor": {"batchSize": 4},
        "explain": True,
        "allowDiskUse": True,
        "maxTimeMS": 0,
        "bypassDocumentValidation": False,
        "readConcern": concern.model_dump(),
        "collation": collation.model_dump(),
        "hint": "active_1",
        "writeConcern": {"w": 2},
        "let": {"x": 1},
    }


async def test_collection_metadata_and_index_management() -> None:
    collection, command = make_collection()
    index = Index("name_1", {"name": IndexDirection.ASCENDING}, unique=True)
    await collection.create_indexes(index, comment="create")
    assert command.await_args is not None
    assert command.await_args.args[0] == {
        "createIndexes": "items",
        "indexes": [index.model_dump()],
        "comment": "create",
    }
    with pytest.raises(ValueError, match="Empty sequence"):
        await collection.create_indexes()
    await collection.drop_indexes(drop_all=True)
    assert command.await_args.args[0] == {
        "dropIndexes": "items",
        "index": "*",
    }
    await collection.re_index()
    assert command.await_args.args[0] == {"reIndex": "items"}

    database = collection.database
    database.list_collections.return_value = [  # pyright: ignore[reportAttributeAccessIssue]
        Collection("items", database, options={"capped": True}),
    ]
    assert await collection.create_if_not_exists() is not None
    assert (await collection.with_options()).options == {"capped": True}
    database.list_collections.return_value = []  # pyright: ignore[reportAttributeAccessIssue]
    database.create_collection = AsyncMock(
        return_value=Collection("items", database),
    )
    with pytest.raises(ValueError, match="namespace"):
        await collection.with_options()
    created = await collection.create_if_not_exists()
    database.create_collection.assert_awaited_once_with("items")
    assert created == database.create_collection.return_value


def test_collection_subcollection_find_and_method_arguments() -> None:
    collection, _ = make_collection()
    database = collection.database

    def side_effect(name: str) -> Collection:
        return Collection(name, database)

    database.get_collection = MagicMock(
        side_effect=side_effect,
    )
    assert collection.archive.name == "items.archive"
    assert collection.x.name == "items.x"
    cursor = collection.find({"active": True})
    assert cursor._query == {  # ruff: ignore[private-member-access] # pyright: ignore[reportPrivateUsage]
        "find": "items",
        "filter": {"active": True},
    }
    typed = collection.find({}, cls=Document)
    assert typed._query == {"find": "items", "filter": {}}  # pyright: ignore[reportPrivateUsage] # ruff: ignore[private-member-access]


async def test_convert_to_capped_validator_and_drop() -> None:
    collection, command = make_collection()
    with pytest.raises(ValueError, match="size below zero"):
        await collection.convert_to_capped(0)

    await collection.convert_to_capped(
        4096,
        WriteConcern(w=1),
        comment="cap",
    )
    assert command.await_args is not None
    assert command.await_args.args[0] == {
        "convertToCapped": "items",
        "size": 4096,
        "comment": "cap",
        "writeConcern": {"w": 1},
    }
    await collection.set_validator({"$jsonSchema": {"bsonType": "object"}})
    assert command.await_args.args[0] == {
        "collMod": "items",
        "validator": {"$jsonSchema": {"bsonType": "object"}},
        "validationLevel": "moderate",
    }
    await collection.drop()
    collection.database.drop_collection.assert_awaited_once_with("items")  # pyright: ignore[reportUnknownMemberType, reportAttributeAccessIssue]
