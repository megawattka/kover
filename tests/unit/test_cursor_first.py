from types import SimpleNamespace
from typing import TYPE_CHECKING, Any
import unittest
from unittest.mock import AsyncMock

from kover.collection import Collection
from kover.cursor import Cursor
from kover.database import Database
from kover.gridfs.gridfs import GridFS
from kover.helpers import raw_decoder
from kover.schema.document import Document

if TYPE_CHECKING:
    from kover.typings import DictT


class InsertDocument(Document):
    value: int


class CommandCursorTests(unittest.IsolatedAsyncioTestCase):
    @staticmethod
    async def test_insert_one_uses_mongodb_id_and_sets_model_id() -> None:
        command = AsyncMock(return_value={"ok": 1})
        database: Any = SimpleNamespace(command=command)
        collection = Collection("items", database)
        document = InsertDocument(value=1)

        document_id = await collection.insert_one(document)

        inserted = command.await_args_list[0].args[0]["documents"][0]
        assert inserted["_id"] == document_id
        assert "id" not in inserted

    @staticmethod
    async def test_insert_many_uses_and_returns_mongodb_ids() -> None:
        command = AsyncMock(return_value={"ok": 1})
        database: Any = SimpleNamespace(command=command)
        collection = Collection("items", database)
        documents = [InsertDocument(value=1), InsertDocument(value=2)]

        document_ids = await collection.insert_many(documents)

        inserted = command.await_args_list[0].args[0]["documents"]
        assert [document["_id"] for document in inserted] == document_ids
        assert all("id" not in document for document in inserted)

    @staticmethod
    async def test_aggregate_explain_returns_document_wo_get_more() -> None:
        response: DictT = {"ok": 1, "queryPlanner": {}}
        command = AsyncMock(return_value=response)
        database: Any = SimpleNamespace(command=command)
        collection = Collection("items", database)
        result = await collection.aggregate([], explain=True).first()
        assert result == response
        command.assert_awaited_once()

    @staticmethod
    async def test_aggregate_reads_all_batches_in_session() -> None:
        command = AsyncMock(side_effect=[
            {"cursor": {"id": 10, "firstBatch": [{"n": 1}]}},
            {"cursor": {"id": 20, "nextBatch": [{"n": 2}]}},
            {"cursor": {"id": 0, "nextBatch": [{"n": 3}]}},
        ])
        database: Any = SimpleNamespace(command=command)
        collection = Collection("items", database)
        session: Any = SimpleNamespace(is_active=True)
        cursor = collection.aggregate(
            [], cursor={"batchSize": 1}, session=session,
        )

        assert await cursor.to_list() == [{"n": 1}, {"n": 2}, {"n": 3}]
        for call in command.await_args_list:
            assert call.kwargs["session"] is session
        assert command.await_args_list[1].args[0]["getMore"] == 10
        assert command.await_args_list[2].args[0]["getMore"] == 20

    @staticmethod
    async def test_list_collections_reads_all_batches() -> None:
        client: Any = SimpleNamespace()
        database = Database("test", client)
        database.command = AsyncMock(side_effect=[
            {"cursor": {"id": 10, "ns": "test.$cmd.listCollections",
                        "firstBatch": [{"name": "one"}]}},
            {"cursor": {"id": 20, "nextBatch": [{"name": "two"}]}},
            {"cursor": {"id": 0, "nextBatch": [{"name": "three"}]}},
        ])
        assert await database.list_collections(name_only=True) == [
            "one", "two", "three",
        ]
        first_command = database.command.await_args_list[0].args[0]
        last_command = database.command.await_args_list[-1].args[0]
        assert first_command["listCollections"] == 1
        assert first_command["filter"] == {}
        assert last_command["collection"] == "$cmd.listCollections"

    @staticmethod
    async def test_list_collections_maps_options_for_all_batches() -> None:
        client: Any = SimpleNamespace()
        database = Database("test", client)
        database.command = AsyncMock(side_effect=[
            {"cursor": {"id": 12, "firstBatch": [
                {"name": "one", "options": {"capped": True}},
            ]}},
            {"cursor": {"id": 0, "nextBatch": [
                {"name": "two", "info": {"readOnly": True}},
            ]}},
        ])

        collections = await database.list_collections()

        assert [collection.name for collection in collections] == [
            "one", "two",
        ]
        assert collections[0].options == {"capped": True}
        assert collections[1].info == {"readOnly": True}

    @staticmethod
    async def test_list_indexes_reads_all_batches() -> None:
        command = AsyncMock(side_effect=[
            {"cursor": {"id": 10, "firstBatch": [
                {"name": "a_1", "key": {"a": 1}},
            ]}},
            {"cursor": {"id": 20, "nextBatch": []}},
            {"cursor": {"id": 0, "nextBatch": [
                {"name": "b_1", "key": {"b": 1}},
            ]}},
        ])
        database: Any = SimpleNamespace(command=command)
        collection = Collection("items", database)
        indexes = await collection.list_indexes()
        assert [index.name for index in indexes] == ["a_1", "b_1"]

    @staticmethod
    async def test_reply_namespace_used_for_get_more_and_close() -> None:
        command = AsyncMock(side_effect=[
            {"cursor": {"id": 10, "ns": "test.actual.items",
                        "firstBatch": [{"n": 1}]}},
            {"cursor": {"id": 20, "nextBatch": [{"n": 2}]}}, {},
        ])
        client: Any = SimpleNamespace(command=command)
        collection = Collection("unused", client)
        cursor: Cursor[DictT] = Cursor({
            "find": 1,
        }, collection, decoder=raw_decoder)
        await anext(cursor)
        await anext(cursor)
        await cursor.close()

        assert command.await_args_list[1].args[0]["collection"] == "actual.items"  # ruff: ignore[line-too-long]
        assert command.await_args_list[-1].args[0]["killCursors"] == "actual.items"  # ruff: ignore[line-too-long]

    @staticmethod
    async def test_command_batch_size_applies_to_initial_and_gm() -> None:
        command = AsyncMock(side_effect=[
            {"cursor": {"id": 10, "ns": "test.items",
                        "firstBatch": [{"n": 1}]}},
            {"cursor": {"id": 0, "ns": "test.items",
                        "nextBatch": [{"n": 2}]}},
        ])
        database: Any = SimpleNamespace(command=command)
        cursor = Collection("items", database).aggregate(
            [{"$match": {}}],
        ).batch_size(2).comment("test")

        command.assert_not_awaited()
        assert await cursor.to_list() == [{"n": 1}, {"n": 2}]
        initial_command = command.await_args_list[0].args[0]
        get_more_command = command.await_args_list[1].args[0]
        assert initial_command["cursor"]["batchSize"] == 2
        assert initial_command["comment"] == "test"
        assert get_more_command["getMore"] == 10
        assert get_more_command["batchSize"] == 2

    @staticmethod
    async def test_aggregate_returns_lc_and_reads_multiple_batches() -> None:
        command = AsyncMock(side_effect=[
            {"cursor": {"id": 10, "ns": "test.items",
                        "firstBatch": [{"n": 1}]}},
            {"cursor": {"id": 0, "ns": "test.items",
                        "nextBatch": [{"n": 2}]}},
        ])
        database: Any = SimpleNamespace(command=command)
        cursor = Collection("items", database).aggregate(
            [{"$match": {}}], cursor={"batchSize": 2},
        )
        command.assert_not_awaited()
        assert await cursor.to_list() == [{"n": 1}, {"n": 2}]
        assert command.await_args_list[0].args[0]["aggregate"] == "items"
        assert command.await_args_list[0].args[0]["cursor"] == {"batchSize": 2}
        assert command.await_args_list[1].args[0]["getMore"] == 10

    async def test_library_owned_cursor_is_closed_on_gm_error(self) -> None:
        command = AsyncMock(side_effect=[
            {"cursor": {"id": 10, "firstBatch": [{"n": 1}]}},
            ValueError("read"), {},
        ])
        database: Any = SimpleNamespace(command=command)
        cursor = Collection("items", database).aggregate([])
        with self.assertRaisesRegex(ValueError, "read"):
            await cursor.to_list()
        assert "killCursors" in command.await_args_list[-1].args[0]

    @staticmethod
    async def test_database_routes_sessions_wo_socket_callback() -> None:
        socket = AsyncMock()
        socket.request.return_value = {"ok": 1}
        client: Any = SimpleNamespace(request=socket.request)
        database = Database("test", client)
        session: Any = SimpleNamespace(client=client)
        response = await database.command({"ping": 1}, session=session)

        assert response == {"ok": 1}
        socket.request.assert_awaited_once_with(
            doc={"ping": 1},
            session=session,
            db_name="test",
            write_concern=None,
        )

    @staticmethod
    async def test_database_routes_operation_write_concern() -> None:
        request = AsyncMock(return_value={"ok": 1})
        client: Any = SimpleNamespace(request=request)
        database = Database("test", client)
        write_concern = SimpleNamespace()
        await database.command(
            {"insert": "items"}, write_concern=write_concern,  # pyright: ignore[reportArgumentType]
        )

        client.request.assert_awaited_once_with(
            doc={"insert": "items"},
            session=None,
            db_name="test",
            write_concern=write_concern,
        )

    async def test_gridfs_list_closes_cursor_on_get_more_error(self) -> None:
        client: Any = SimpleNamespace()
        database = Database("test", client)
        database.command = AsyncMock(side_effect=[
            {"cursor": {"id": 10, "firstBatch": [{
                "length": 1,
                "upload_date": "2025-01-01T00:00:00Z",
                "chunk_size": 1,
            }]}},
            ValueError("read"), {"ok": 1},
        ])
        with self.assertRaisesRegex(ValueError, "read"):
            await GridFS(database).list()

        assert database.command.await_args_list[-1].args[0] == {
            "killCursors": "fs.files", "cursors": [10],
        }

    async def test_database_rejects_tx_from_another_connection(self) -> None:
        socket = AsyncMock()
        client: Any = SimpleNamespace(request=socket.request)
        session: Any = SimpleNamespace(
            client=AsyncMock(),
        )
        database = Database("test", client)
        with self.assertRaises(ValueError):
            await database.command({"ping": 1}, session=session)

        socket.request.assert_not_awaited()
