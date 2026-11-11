from __future__ import annotations

import asyncio
from contextlib import suppress
from datetime import UTC, datetime
from functools import partial
import struct
from typing import Any

import elune
import pytest

from kover import from_uri


def reply(request_id: int, response: dict[str, Any]) -> bytes:
    payload = bytes(5) + elune.encode(response)
    return (
        struct.pack("<iiii", len(payload) + 16, 1, request_id, 2013) + payload
    )


def hello_response(role: str, addresses: dict[str, str]) -> dict[str, Any]:
    return {
        "localTime": datetime.now(UTC),
        "connectionId": 1,
        "isWritablePrimary": role == "primary",
        "secondary": role == "secondary",
        "setName": "rs",
        "hosts": list(addresses.values()),
        "passives": [],
        "arbiters": [],
        "me": addresses[role],
        "primary": addresses["primary"],
    }


async def read_command(
    reader: asyncio.StreamReader,
) -> tuple[int, dict[str, Any]]:
    length, request_id, _, opcode = struct.unpack(
        "<iiii",
        await reader.readexactly(16),
    )
    assert opcode == 2013
    body = await reader.readexactly(length - 16)
    return request_id, elune.decode(body[5:])  # pyright: ignore[reportUnknownMemberType]


@pytest.mark.parametrize(
    "mode",
    [
        "primary",
        "primaryPreferred",
        "secondary",
        "secondaryPreferred",
        "nearest",
    ],
)
async def test_wire_discovery_follows_replica_members(mode: str) -> None:  # ruff: ignore[complex-structure, too-many-statements]
    commands: dict[str, list[dict[str, Any]]] = {
        "secondary": [],
        "primary": [],
    }
    tasks: set[asyncio.Task[None]] = set()
    addresses: dict[str, str] = {}
    errors: list[BaseException] = []
    source = ""

    async def serve(
        role: str,
        reader: asyncio.StreamReader,
        writer: asyncio.StreamWriter,
    ) -> None:
        task = asyncio.current_task()
        if task is not None:
            tasks.add(task)
        try:  # ruff: ignore[too-many-statements-in-try-clause]
            while True:
                request_id, command = await read_command(reader)
                commands[role].append(command)
                response: dict[str, Any] = {"ok": 1}
                if "hello" in command:
                    response.update(hello_response(role, addresses))
                elif "find" in command:
                    response["cursor"] = {
                        "id": elune.Int64(42),
                        "ns": "test.items",
                        "firstBatch": [{"server": role, "batch": 1}],
                    }
                elif "getMore" in command:
                    response["cursor"] = {
                        "id": elune.Int64(42),
                        "ns": "test.items",
                        "nextBatch": [{"server": role, "batch": 2}],
                    }
                writer.write(reply(request_id, response))
                await writer.drain()
        except asyncio.IncompleteReadError:
            pass
        except (AssertionError, OSError, ValueError) as error:
            errors.append(error)
        finally:
            writer.close()
            with suppress(OSError):
                await writer.wait_closed()
            if task is not None:
                tasks.discard(task)

    async with (
        await asyncio.start_server(
            partial(serve, "secondary"),
            "127.0.0.1",
            0,
        ) as secondary_server,
        await asyncio.start_server(
            partial(serve, "primary"),
            "127.0.0.1",
            0,
        ) as primary_server,
    ):
        secondary_port = secondary_server.sockets[0].getsockname()[1]
        primary_port = primary_server.sockets[0].getsockname()[1]
        addresses.update(
            {
                "secondary": f"127.0.0.1:{secondary_port}",
                "primary": f"127.0.0.1:{primary_port}",
            },
        )
        # The first seed speaks TCP but cannot speak MongoDB.

        async def broken(
            _reader: asyncio.StreamReader,
            writer: asyncio.StreamWriter,
        ) -> None:
            writer.close()
            await writer.wait_closed()

        async with await asyncio.start_server(broken, "127.0.0.1", 0) as dead:
            try:
                async with await from_uri(
                    f"mongodb://127.0.0.1:{dead.sockets[0].getsockname()[1]},"
                    f"{addresses['secondary']}/?replicaSet=rs"
                    "&serverSelectionTimeoutMS=1000&connectTimeoutMS=100"
                    f"&readPreference={mode}",
                ) as client:
                    assert await client.command({"ping": 1}) == {"ok": 1}
                    collection = client.get_database("test").get_collection(
                        "items",
                    )
                    async with collection.find({}) as cursor:
                        first = await anext(cursor)
                        source = first["server"]
                        second = await anext(cursor)
                        assert first["server"] == second["server"]
                    await client.command(
                        {"insert": "items", "documents": [{"x": 1}]},
                    )
                    if mode == "nearest":
                        assert first["server"] in {"primary", "secondary"}
                    else:
                        expected = (
                            "secondary"
                            if mode in {"secondary", "secondaryPreferred"}
                            else "primary"
                        )
                        assert first["server"] == expected
            finally:
                await asyncio.gather(*tasks)
    assert not errors
    for role, received in commands.items():
        cursor_commands = [
            command
            for command in received
            if any(
                name in command for name in ("find", "getMore", "killCursors")
            )
        ]
        if role == source:
            assert [next(iter(command)) for command in cursor_commands] == [
                "find",
                "getMore",
                "killCursors",
            ]
            assert cursor_commands[0].get("$readPreference") == (
                None if mode == "primary" else {"mode": mode}
            )
            assert all(
                "$readPreference" not in command
                for command in cursor_commands[1:]
            )
        else:
            assert not cursor_commands
    assert commands["primary"][-1]["insert"] == "items"
    assert all("insert" not in command for command in commands["secondary"])
