from __future__ import annotations

import asyncio
from typing import TYPE_CHECKING
from unittest.mock import AsyncMock, MagicMock

import pytest

from kover import Collation, Kover
from kover.cursor import Cursor
from kover.helpers import raw_decoder
from kover.network.pool import ConnectionPool

if TYPE_CHECKING:
    from kover.typings import DictT


def make_cursor(
    command: AsyncMock, query: DictT,
) -> Cursor[DictT]:
    client = Kover(pool=MagicMock(spec=ConnectionPool))
    collection = client.get_database("test").get_collection("items")
    collection.database.command = command
    return Cursor(query, collection, raw_decoder)


async def test_command_result_is_cached_and_not_yielded_twice() -> None:
    command = AsyncMock(return_value={"ok": 1, "queryPlanner": {}})
    cursor = make_cursor(command, {"aggregate": "items", "explain": True})
    assert await cursor.command_result() == {"ok": 1, "queryPlanner": {}}
    assert await cursor.command_result() == {"ok": 1, "queryPlanner": {}}
    assert await cursor.to_list() == []
    command.assert_awaited_once()


async def test_command_result_rejects_cursor_and_kills_it() -> None:
    command = AsyncMock(
        side_effect=[
            {"cursor": {"id": 42, "firstBatch": []}},
            {"ok": 1},
        ],
    )
    cursor = make_cursor(command, {"find": "items"})
    with pytest.raises(RuntimeError, match="returned a cursor"):
        await cursor.command_result()

    assert command.await_args is not None
    assert command.await_args.args[0] == {
        "killCursors": "items",
        "cursors": [42],
    }
    assert await cursor.to_list() == []


@pytest.mark.parametrize("namespace", ["invalid", "test.", ""])
async def test_invalid_server_namespace_fails_and_cleans_up(
    namespace: str,
) -> None:
    command = AsyncMock(
        side_effect=[
            {"cursor": {"id": 42, "ns": namespace, "firstBatch": []}},
            {},
        ],
    )
    cursor = make_cursor(command, {"find": "items"})
    with pytest.raises(ValueError, match="namespace"):
        await cursor.to_list()
    assert command.await_args is not None
    assert command.await_args.args[0] == {
        "killCursors": "items",
        "cursors": [42],
    }


async def test_negative_limit_single_batch_and_copied_option_maps() -> None:
    command = AsyncMock(return_value={"cursor": {"id": 0, "firstBatch": []}})
    query: DictT = {"find": "items"}
    cursor = make_cursor(command, query)
    mapping = {"value": 1}
    cursor.limit(-3).sort(mapping).projection(mapping).hint(mapping)
    cursor.collation(Collation(locale="en"))
    mapping["value"] = -1
    await cursor.to_list()
    assert command.await_args is not None
    sent = command.await_args.args[0]
    assert sent["limit"] == 3
    assert sent["singleBatch"] is True
    assert sent["sort"] == sent["projection"] == sent["hint"] == {"value": 1}
    assert sent["collation"]["locale"] == "en"
    assert query == {"find": "items"}


async def test_unknown_command_batch_size_is_rejected_without_io() -> None:
    command = AsyncMock()
    cursor = make_cursor(command, {"ping": 1}).batch_size(2)
    with pytest.raises(ValueError, match="batchSize placement"):
        await cursor.to_list()
    command.assert_not_awaited()


class CursorInterrupted(BaseException):
    """An interruption requiring cleanup outside Exception's hierarchy."""


@pytest.mark.parametrize(
    "error_type",
    [RuntimeError, asyncio.CancelledError, CursorInterrupted],
)
async def test_cursor_preserves_failure_and_cleanup_failure(
    error_type: type[BaseException],
) -> None:
    original = error_type("original")
    cleanup_error = OSError("cleanup")
    command = AsyncMock(side_effect=[
        {"cursor": {"id": 42, "firstBatch": []}},
        original, cleanup_error,
    ])
    cursor = make_cursor(command, {"find": "items"})
    with pytest.raises(error_type) as caught:
        await cursor.to_list()
    assert caught.value is original
    assert caught.value.__cause__ is cleanup_error
    assert any("cleanup" in note for note in caught.value.__notes__)
    assert command.await_args is not None
    assert command.await_args.args[0] == {
        "killCursors": "items", "cursors": [42],
    }
    await cursor.close()
    assert await cursor.to_list() == []


@pytest.mark.parametrize(
    "error_type", [RuntimeError, asyncio.CancelledError, CursorInterrupted],
)
async def test_command_result_failure_closes_locally(
    error_type: type[BaseException],
) -> None:
    original = error_type("command failed")
    command = AsyncMock(side_effect=original)
    cursor = make_cursor(command, {"aggregate": "items", "explain": True})
    with pytest.raises(error_type) as caught:
        await cursor.command_result()
    assert caught.value is original
    await cursor.close()
    assert await cursor.to_list() == []
    command.assert_awaited_once()


async def test_command_result_cleanup_failure_preserves_command_err() -> None:
    cleanup_error = OSError("cleanup")
    command = AsyncMock(side_effect=[
        {"cursor": {"id": 42, "firstBatch": []}}, cleanup_error,
    ])
    cursor = make_cursor(command, {"find": "items"})
    with pytest.raises(RuntimeError, match="returned a cursor") as caught:
        await cursor.command_result()
    assert caught.value.__cause__ is cleanup_error
    assert any("cleanup" in note for note in caught.value.__notes__)
    await cursor.close()


@pytest.mark.parametrize(
    "cleanup_type",
    [asyncio.CancelledError, CursorInterrupted],
)
async def test_context_cleanup_preserves_original_exception(
    cleanup_type: type[BaseException],
) -> None:
    cleanup_error = cleanup_type("cleanup interrupted")
    command = AsyncMock(side_effect=[
        {"cursor": {"id": 42, "firstBatch": [{"value": 1}]}},
        cleanup_error,
    ])
    cursor = make_cursor(command, {"find": "items"})
    original = ValueError("body")

    async def body() -> None:
        async with cursor:
            await anext(cursor)
            raise original

    with pytest.raises(ValueError, match="body") as caught:
        await body()
    assert caught.value is original
    assert caught.value.__cause__ is cleanup_error
    assert any(
        "cleanup interrupted" in note for note in caught.value.__notes__
    )
    await cursor.close()
