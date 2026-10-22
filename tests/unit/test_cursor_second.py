from __future__ import annotations

import asyncio
from types import SimpleNamespace
from typing import TYPE_CHECKING, Any, NoReturn, TypeVar
import unittest
from unittest.mock import AsyncMock, sentinel

from bson import Int64

from kover.collection import Collection
from kover.cursor import Cursor
from kover.database import Database
from kover.helpers import raw_decoder
from kover.schema import Document

if TYPE_CHECKING:
    from kover.typings import JsonT


T_co = TypeVar("T_co", bound=Document, covariant=True)


def batch(
    cursor_id: int,
    documents: list[JsonT],
    *,
    first: bool = False,
) -> JsonT:
    """Generate test batches.

    Returns:
        Test sample documents.
    """
    return {"cursor": {
        "id": Int64(cursor_id),
        "firstBatch" if first else "nextBatch": documents,
    }}


class Item(Document):
    value: int


class CursorTests(unittest.IsolatedAsyncioTestCase):
    def make_cursor(
        self,
        responses: Any,  # ruff: ignore[any-type]
        cls: Any = None,  # ruff: ignore[any-type]
        transaction: Any = None,  # ruff: ignore[any-type]
    ) -> Cursor[Any]:
        self.command = AsyncMock(
            side_effect=responses if responses is not None else (),
        )
        client: Any = SimpleNamespace(request=self.command)
        database = Database("test", client)
        self.database = database
        collection = Collection("items", database)
        if transaction is sentinel.transaction:
            transaction = SimpleNamespace(client=client)

        return Cursor(  # pyright: ignore[reportReturnType]
            {"find": "items", "filter": {}},
            collection,
            decoder=cls.from_document if cls is not None else raw_decoder,
            transaction=transaction,  # pyright: ignore[reportArgumentType]
        )

    async def test_reads_all_batches_and_updates_id(self) -> None:
        cursor: Cursor[JsonT] = self.make_cursor([
            batch(10, [{"value": 1}], first=True),
            batch(20, [{"value": 2}]),
            batch(0, [{"value": 3}]),
        ]).batch_size(1)
        assert await cursor.to_list() == [
            {"value": 1}, {"value": 2}, {"value": 3},
        ]
        calls = self.command.await_args_list
        assert len(calls) == 3
        assert calls[1].kwargs["doc"]["getMore"] == 10
        assert calls[2].kwargs["doc"]["getMore"] == 20
        assert isinstance(calls[2].kwargs["doc"]["getMore"], Int64)
        assert calls[1].kwargs["doc"]["batchSize"] == 1
        with self.assertRaises(StopAsyncIteration):
            await anext(cursor)
        assert self.command.await_count == 3

    async def test_empty_batches_do_not_end_live_cursor(self) -> None:
        cursor = self.make_cursor([
            batch(10, [], first=True), batch(10, []),
            batch(0, [{"value": 1}]),
        ])
        assert await cursor.to_list() == [{"value": 1}]

    async def test_empty_exhausted_cursor(self) -> None:
        cursor = self.make_cursor([batch(0, [], first=True)])
        assert await cursor.to_list() == []
        assert await cursor.to_list() == []
        self.command.assert_awaited_once()

    async def test_first_repeated_calls_return_same_document(self) -> None:
        cursor = self.make_cursor([
            batch(10, [{"value": 1}, {"value": 2}], first=True),
        ])

        assert await cursor.first() == {"value": 1}
        assert await cursor.first() == {"value": 1}
        assert await cursor.to_list() == [{"value": 2}]

    async def test_first_returns_first_remaining_document(self) -> None:
        cursor = self.make_cursor([
            batch(10, [{"value": 1}, {"value": 2}], first=True),
        ])

        assert await anext(cursor) == {"value": 1}
        assert await cursor.first() == {"value": 2}
        assert await cursor.first() == {"value": 2}

    async def test_first_on_empty_cursor_raises_stop_async_iteration(
        self,
    ) -> None:
        cursor = self.make_cursor([batch(0, [], first=True)])

        with self.assertRaises(StopAsyncIteration):
            await cursor.first()
        self.command.assert_awaited_once()

    async def test_close_before_iteration_never_sends_find(self) -> None:
        cursor = self.make_cursor([])
        await cursor.close()
        assert await cursor.to_list() == []
        self.command.assert_not_awaited()

    async def test_close_discards_buffer_and_kills_without_limit(self) -> None:
        cursor = self.make_cursor([
            batch(10, [{"value": 1}, {"value": 2}], first=True), {},
        ])
        await anext(cursor)
        await cursor.close()
        await cursor.close()
        assert await cursor.to_list() == []
        assert self.command.await_count == 2
        assert self.command.await_args_list[-1].kwargs["doc"] == {
            "killCursors": "items", "cursors": [Int64(10)],
        }

    async def test_context_preserves_exception_and_closes(self) -> None:
        cursor = self.make_cursor([
            batch(10, [{"value": 1}], first=True), {},
        ])
        with self.assertRaisesRegex(ValueError, "body"):
            async with cursor:
                await anext(cursor)
                raise ValueError("body")
        assert "killCursors" in self.command.await_args_list[-1].kwargs["doc"]

    async def test_cleanup_error_propagates_with_body_as_context(self) -> None:
        cursor = self.make_cursor([
            batch(10, [{"value": 1}], first=True), OSError("cleanup"),
        ])
        with self.assertRaisesRegex(ValueError, "body") as caught:
            async with cursor:
                await anext(cursor)
                raise ValueError("body")
        assert any("cleanup" in note for note in caught.exception.__notes__)

    async def test_model_conversion_for_every_batch(self) -> None:
        cursor: Cursor[Item] = self.make_cursor([
            batch(10, [{"value": 1}], first=True),
            batch(0, [{"value": 2}]),
        ], cls=Item)
        items = await cursor.to_list()
        assert all(isinstance(item, Item) for item in items)  # pyright: ignore[reportUnnecessaryIsInstance]
        assert [item.value for item in items] == [1, 2]

    async def test_conversion_error_requires_explicit_close(self) -> None:
        cursor = self.make_cursor([
            batch(10, [{"value": 1}], first=True), {},
        ], cls=Item)

        def throw_on_decode(_document: JsonT) -> NoReturn:
            raise ValueError("decode")

        cursor._decoder = throw_on_decode  # pyright: ignore[reportPrivateUsage] # ruff: ignore[private-member-access]
        with self.assertRaises(ValueError):
            await anext(cursor)

        assert self.command.await_count == 2
        with self.assertRaises(StopAsyncIteration):
            await anext(cursor)
        await cursor.close()
        assert self.command.await_count == 2
        assert await cursor.to_list() == []

    async def test_get_more_error_leaves_cleanup_to_owner(self) -> None:
        cursor = self.make_cursor([
            batch(10, [{"value": 1}], first=True),
            ValueError("read"), OSError("cleanup"),
        ])
        with self.assertRaisesRegex(ValueError, "read"):
            await cursor.to_list()
        assert self.command.await_count == 3
        await cursor.close()
        assert await cursor.to_list() == []

    async def test_transaction_propagated_to_all_commands(self) -> None:
        cursor = self.make_cursor([
            batch(10, [{"value": 1}], first=True),
            batch(20, [{"value": 2}]), {},
        ], transaction=sentinel.transaction)
        await anext(cursor)
        await anext(cursor)
        await cursor.close()
        assert self.command.await_count == 3
        for call in self.command.await_args_list:
            assert call.kwargs["transaction"].client is self.database.client

    async def test_options_cannot_change_after_start(self) -> None:
        cursor = self.make_cursor([batch(0, [{"value": 1}], first=True)])
        await anext(cursor)
        for method, value in [
            ("sort", {"value": 1}), ("skip", 1), ("limit", 1),
            ("batch_size", 1), ("projection", {"value": 1}),
            ("comment", "changed"), ("hint", "index"),
        ]:
            with self.subTest(method=method), self.assertRaises(RuntimeError):
                getattr(cursor, method)(value)

    async def test_invalid_numeric_options(self) -> None:
        cursor = self.make_cursor([])
        for method in ("skip", "limit", "batch_size"):
            with self.subTest(method=method):
                assert getattr(cursor, method)(-1) is cursor

    async def test_query_options_and_zero_batch_size(self) -> None:
        cursor = self.make_cursor([
            batch(10, [], first=True), batch(0, [{"value": 1}]),
        ])
        cursor.sort({"value": 1}).skip(2).limit(3).batch_size(0)
        cursor.projection({"value": 1}).comment("test").hint("value_1")
        assert await cursor.to_list() == [{"value": 1}]
        query = self.command.await_args_list[0].kwargs["doc"]
        last_doc = self.command.await_args_list[-1].kwargs["doc"]
        assert query["skip"] == 2
        assert query["limit"] == 3
        assert query["batchSize"] == 0
        assert "batchSize" not in last_doc

    async def test_cancelled_get_more_requires_explicit_close(self) -> None:
        cursor = self.make_cursor([
            batch(10, [{"value": 1}], first=True),
            asyncio.CancelledError(), {},
        ])
        await anext(cursor)
        with self.assertRaises(asyncio.CancelledError):
            await anext(cursor)
        assert self.command.await_count == 3
        await cursor.close()
        assert "killCursors" in self.command.await_args_list[-1].kwargs["doc"]
        assert await cursor.to_list() == []

    async def test_concurrent_reads_rejected_without_duplicate_find(
        self,
    ) -> None:
        cursor = self.make_cursor([])
        entered, release = asyncio.Event(), asyncio.Event()

        async def respond(*_args: object, **_kwargs: object) -> JsonT:
            entered.set()
            await release.wait()
            return batch(0, [{"value": 1}], first=True)

        self.command.side_effect = respond
        task = asyncio.create_task(anext(cursor))
        try:
            await asyncio.wait_for(entered.wait(), 1)
            with self.assertRaises(RuntimeError):
                await anext(cursor)
            with self.assertRaises(RuntimeError):
                await cursor.close()
        finally:
            release.set()
            assert await task == {"value": 1}
        self.command.assert_awaited_once()


if __name__ == "__main__":
    unittest.main()
