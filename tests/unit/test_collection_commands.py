from __future__ import annotations

from unittest.mock import AsyncMock, MagicMock

from bson import ObjectId
import pytest

from kover import Document, Kover, ReadConcern, Update, WriteConcern
from kover.enums import ValidationLevel
from kover.network.pool import ConnectionPool


class Item(Document):
    value: int


async def test_insert_ids_and_caller_documents_are_preserved() -> None:
    collection = (
        Kover(pool=MagicMock(spec=ConnectionPool))
        .get_database("test")
        .get_collection("items")
    )
    command = AsyncMock(return_value={"ok": 1})
    collection.database.command = command
    identifier = ObjectId()
    original = {"_id": identifier, "value": 1}
    assert await collection.insert_one(original) == identifier
    assert original == {"_id": identifier, "value": 1}
    repeated = {"value": 2}
    ids = await collection.insert_many([repeated, repeated])
    assert len(set(ids)) == 2
    assert repeated == {"value": 2}
    model = Item(value=3).set_object_id(identifier)
    assert await collection.insert_one(model) == identifier
    assert await collection.insert_many([model]) == [identifier]


async def test_collection_management_and_validator_commands() -> None:
    collection = (
        Kover(pool=MagicMock(spec=ConnectionPool))
        .get_database("test")
        .get_collection("items")
    )
    command = AsyncMock(return_value={"ok": 1})
    collection.database.command = command
    collection.database.list_collections = AsyncMock(return_value=[])
    created = await collection.create_if_not_exists()
    assert created.name == "items"
    command.assert_awaited_with({"create": "items"})
    collection.database.list_collections.return_value = [created]
    assert await collection.create_if_not_exists() is created
    assert await collection.with_options() is created
    collection.database.list_collections.return_value = []
    with pytest.raises(ValueError, match="namespace"):
        await collection.with_options()
    await collection.set_validator(
        {"value": {"$gt": 0}}, level=ValidationLevel.STRICT,
    )
    command.assert_awaited_with(
        {
            "collMod": "items",
            "validator": {"value": {"$gt": 0}},
            "validationLevel": "strict",
        },
    )
    for size in (0, -1):
        with pytest.raises(ValueError, match="size"):
            await collection.convert_to_capped(size)
    await collection.convert_to_capped(1024, WriteConcern(w=2), "test")
    command.assert_awaited_with(
        {
            "convertToCapped": "items",
            "size": 1024,
            "writeConcern": {"w": 2},
            "comment": "test",
        },
    )
    with pytest.raises(ValueError, match="Empty sequence"):
        await collection.create_indexes()
    await collection.drop_indexes(drop_all=True)
    command.assert_awaited_with({"dropIndexes": "items", "index": "*"})
    await collection.drop_indexes(["one", "two"])
    command.assert_awaited_with(
        {"dropIndexes": "items", "index": ["one", "two"]},
    )
    await collection.re_index()
    command.assert_awaited_with({"reIndex": "items"})


async def test_distinct_count_update_and_index_type_mapping() -> None:
    collection = (
        Kover(pool=MagicMock(spec=ConnectionPool))
        .get_database("test")
        .get_collection("items")
    )
    command = AsyncMock(return_value={"values": [1, 2]})
    collection.database.command = command
    assert await collection.distinct(
        "value", {"active": True}, read_concern=ReadConcern(level="majority"),
    ) == [1, 2]
    assert command.await_args is not None
    assert command.await_args.args[0]["readConcern"] == {"level": "majority"}
    command.return_value = {"n": 5}
    assert await collection.count({"active": True}, limit=10, skip=2) == 5
    assert command.await_args is not None
    sent = command.await_args.args[0]
    assert (sent["limit"], sent["skip"]) == (10, 2)
    command.return_value = {"nModified": 2}
    assert (
        await collection.update(Update({}, {"$inc": {"value": 1}}, multi=True))
        == 2
    )
    command.return_value = {
        "cursor": {
            "id": 0,
            "firstBatch": [
                {"name": "text", "key": {"value": "text"}, "hidden": True},
            ],
        },
    }
    indexes = await collection.list_indexes()
    assert indexes[0].hidden
    assert indexes[0].key["value"] == "text"
