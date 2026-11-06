from __future__ import annotations

import asyncio
from typing import Any
from unittest.mock import AsyncMock, MagicMock

from bson import Int64
import pytest

from kover._utils import raw_decoder  # ruff: ignore[import-private-name]
from kover.client import Kover
from kover.cursor import Cursor
from kover.execution.executor import CommandExecutor
from kover.models.address import Address
from kover.models.hello import HelloResult
from kover.models.read_preference import ReadPreference
from kover.models.topology import ServerDescription
from kover.session import Session


def batch(
    cursor_id: int,
    documents: list[dict[str, Any]],
    *,
    first: bool = False,
    namespace: str = "shop.items",
) -> dict[str, Any]:
    return {
        "cursor": {
            "id": Int64(cursor_id),
            "ns": namespace,
            "firstBatch" if first else "nextBatch": documents,
        },
    }


def setup_cursor(
    replies: list[object],
    query: dict[str, Any] | None = None,
) -> tuple[Cursor[dict[str, Any]], Kover, MagicMock, MagicMock]:
    address = Address(host="secondary")
    selector = MagicMock()
    selector.direct_connection = False
    selector.select = AsyncMock(return_value=address)
    selector.description.return_value = ServerDescription(
        address=address,
        hello=HelloResult(setName="rs", secondary=True),
    )
    pools = MagicMock()
    pools.close = AsyncMock()
    pools.for_server.return_value.execute = AsyncMock(side_effect=replies)
    client = Kover(CommandExecutor(selector=selector, pools=pools))
    collection = client.get_database("shop").get_collection("items")
    cursor = Cursor(
        query if query is not None else {"find": "items"},
        collection,
        raw_decoder,
    )
    return cursor, client, selector, pools


async def test_batches_use_new_api_and_keep_server_affinity() -> None:
    cursor, client, selector, pools = setup_cursor(
        [
            batch(10, [{"v": 1}], first=True),
            batch(20, []),
            batch(0, [{"v": 2}]),
        ],
    )
    preference = ReadPreference(mode="secondary")
    cursor.read_preference(preference).batch_size(1)
    assert await cursor.to_list() == [{"v": 1}, {"v": 2}]
    selector.select.assert_awaited_once_with(preference, deadline=None)
    calls = pools.for_server.return_value.execute.await_args_list
    assert calls[0].args[0]["$readPreference"] == {"mode": "secondary"}
    assert [call.args[0]["getMore"] for call in calls[1:]] == [10, 20]
    assert all(call.args[0]["batchSize"] == 1 for call in calls)
    assert all(call.kwargs["database"] == "shop" for call in calls)
    assert all(
        call.args[0] == Address(host="secondary")
        for call in pools.for_server.call_args_list
    )
    await cursor.close()
    assert len(calls) == 3
    await client.close()


async def test_server_namespace_used_for_get_more_and_kill() -> None:
    cursor, client, selector, pools = setup_cursor(
        [
            batch(
                10, [{"v": 1}], first=True, namespace="other.items.with.dots",
            ),
            batch(20, [{"v": 2}], namespace="other.items.with.dots"),
            {"ok": 1},
        ],
    )
    assert await anext(cursor) == {"v": 1}
    assert await anext(cursor) == {"v": 2}
    await cursor.close()
    calls = pools.for_server.return_value.execute.await_args_list
    assert calls[0].kwargs["database"] == "shop"
    assert calls[1].kwargs["database"] == "other"
    assert calls[1].args[0]["collection"] == "items.with.dots"
    assert calls[2].kwargs["database"] == "other"
    assert calls[2].args[0] == {
        "killCursors": "items.with.dots",
        "cursors": [20],
    }
    assert selector.select.await_count == 1
    await client.close()


@pytest.mark.parametrize("namespace", ["invalid", "shop.", ".items", ""])
async def test_invalid_namespace_kills_cursor(namespace: str) -> None:
    cursor, client, _, pools = setup_cursor(
        [
            batch(10, [], first=True, namespace=namespace),
            {"ok": 1},
        ],
    )
    with pytest.raises(ValueError, match="namespace"):
        await cursor.to_list()
    assert pools.for_server.return_value.execute.await_args.args[0] == {
        "killCursors": "items",
        "cursors": [10],
    }
    await cursor.close()
    assert await cursor.to_list() == []
    await client.close()


@pytest.mark.parametrize(
    "error",
    [ValueError("read"), asyncio.CancelledError()],
)
async def test_read_failure_or_cancellation_cleans_up(
    error: BaseException,
) -> None:
    cursor, client, selector, pools = setup_cursor(
        [
            batch(10, [{"v": 1}], first=True),
            error,
            {"ok": 1},
        ],
    )
    await anext(cursor)
    with pytest.raises(type(error)) as caught:
        await anext(cursor)
    assert caught.value is error
    calls = pools.for_server.return_value.execute.await_args_list
    assert calls[-1].args[0] == {"killCursors": "items", "cursors": [10]}
    assert selector.select.await_count == 1
    await cursor.close()
    assert await cursor.to_list() == []
    await client.close()


async def test_decoder_failure_preserves_error_if_cleanup_fails() -> None:
    cursor, client, _, _ = setup_cursor(
        [
            batch(10, [{"v": 1}], first=True),
            OSError("cleanup failed"),
        ],
    )
    error = ValueError("decode failed")

    def decode(_: dict[str, Any]) -> dict[str, Any]:
        raise error

    cursor = Cursor({"find": "items"}, client.shop.items, decode)
    with pytest.raises(ValueError, match="decode failed") as caught:
        await anext(cursor)
    assert caught.value is error
    assert isinstance(error.__cause__, OSError)
    assert error.__notes__
    await cursor.close()
    await client.close()


@pytest.mark.parametrize(
    "command",
    ["aggregate", "listCollections", "bulkWrite"],
)
async def test_command_cursor_batch_options(command: str) -> None:
    query = {command: "items", "cursor": {"other": True}}
    cursor, client, _, pools = setup_cursor(
        [
            batch(10, [], first=True),
            batch(0, [{"v": 1}]),
        ],
        query,
    )
    cursor.batch_size(0)
    assert await cursor.to_list() == [{"v": 1}]
    calls = pools.for_server.return_value.execute.await_args_list
    assert calls[0].args[0]["cursor"] == {"other": True, "batchSize": 0}
    assert "batchSize" not in calls[1].args[0]
    assert query == {command: "items", "cursor": {"other": True}}
    await client.close()


async def test_bulk_write_batch_size_without_explicit_cursor_option() -> None:
    cursor, client, _, pools = setup_cursor(
        [
            batch(0, [], first=True),
        ],
        {"bulkWrite": 1, "ops": [], "nsInfo": []},
    )
    await cursor.batch_size(5).to_list()
    assert pools.for_server.return_value.execute.await_args.args[0][
        "cursor"
    ] == {"batchSize": 5}
    await client.close()


async def test_command_result_is_cached_and_not_iterated() -> None:
    cursor, client, _, pools = setup_cursor(
        [
            {"ok": 1, "queryPlanner": {}},
        ],
        {"explain": {"find": "items"}},
    )
    reply = await cursor.command_result()
    assert await cursor.command_result() is reply
    assert await cursor.to_list() == []
    pools.for_server.return_value.execute.assert_awaited_once()
    await client.close()


async def test_session_reaches_initial_get_more_and_kill_commands() -> None:
    _, client, selector, pools = setup_cursor(
        [
            batch(10, [{"v": 1}], first=True),
            batch(20, [{"v": 2}]),
            {"ok": 1},
        ],
    )
    session = Session({"id": "session"}, client)
    cursor = Cursor({"find": "items"}, client.shop.items, raw_decoder, session)
    await anext(cursor)
    await anext(cursor)
    await cursor.close()
    calls = pools.for_server.return_value.execute.await_args_list
    assert len(calls) == 3
    assert all(call.args[0]["lsid"] == session.document for call in calls)
    assert selector.select.await_count == 1
    await client.close()


async def test_concurrent_reads_and_close_are_rejected() -> None:
    cursor, client, _, pools = setup_cursor([])
    entered, release = asyncio.Event(), asyncio.Event()

    async def respond(*_args: object, **_kwargs: object) -> dict[str, Any]:
        entered.set()
        await release.wait()
        return batch(0, [{"v": 1}], first=True)

    pools.for_server.return_value.execute.side_effect = respond
    task = asyncio.create_task(anext(cursor))
    try:
        await asyncio.wait_for(entered.wait(), 1)
        with pytest.raises(RuntimeError, match="Concurrent"):
            await anext(cursor)
        with pytest.raises(RuntimeError, match="Concurrent"):
            await cursor.close()
    finally:
        release.set()
        assert await task == {"v": 1}
        await client.close()


async def test_first_caches_and_remaining_final_batch_is_consumed() -> None:
    cursor, client, _, pools = setup_cursor(
        [
            batch(0, [{"v": 1}, {"v": 2}], first=True),
        ],
    )
    assert await cursor.first() == {"v": 1}
    assert await cursor.first() == {"v": 1}
    assert await cursor.to_list() == [{"v": 2}]
    assert await cursor.to_list() == []
    pools.for_server.return_value.execute.assert_awaited_once()
    await client.close()


async def test_context_manager_closes_live_cursor_after_body_error() -> None:
    cursor, client, _, pools = setup_cursor(
        [
            batch(10, [{"v": 1}], first=True),
            {"ok": 1},
        ],
    )
    error = RuntimeError("body failed")

    async def fail_inside_context() -> None:
        async with cursor:
            await anext(cursor)
            raise error

    with pytest.raises(RuntimeError, match="body failed") as caught:
        await fail_inside_context()
    assert caught.value is error
    assert pools.for_server.return_value.execute.await_args.args[0] == {
        "killCursors": "items",
        "cursors": [10],
    }
    assert await cursor.to_list() == []
    await client.close()


async def test_client_bulk_write_cursor_uses_admin_and_server_namespace() -> (
    None
):
    _, client, selector, pools = setup_cursor(
        [
            batch(10, [], first=True, namespace="admin.$cmd.bulkWrite"),
            batch(0, [{"ok": 1}], namespace="admin.$cmd.bulkWrite"),
        ],
    )
    cursor = client.bulk_write({"bulkWrite": 1, "ops": [], "nsInfo": []})
    assert await cursor.batch_size(1).to_list() == [{"ok": 1}]
    calls = pools.for_server.return_value.execute.await_args_list
    assert calls[0].args[0]["cursor"] == {"batchSize": 1}
    assert calls[1].args[0]["collection"] == "$cmd.bulkWrite"
    assert all(call.kwargs["database"] == "admin" for call in calls)
    assert selector.select.await_count == 1
    await client.close()
