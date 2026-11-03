from io import BytesIO
from pathlib import Path
from unittest.mock import AsyncMock, MagicMock

from bson import Binary
import pytest

from kover import Kover
from kover.gridfs import GridFS
from kover.gridfs.exceptions import IncorrectGridFSData
from kover.network.pool import ConnectionPool


async def test_gridfs_path_and_invalid_payload(tmp_path: Path) -> None:
    database = Kover(pool=MagicMock(spec=ConnectionPool)).get_database("test")
    command = AsyncMock(return_value={"ok": 1})
    database.command = command
    fs = GridFS(database)
    path = tmp_path / "payload.bin"
    path.write_bytes(b"payload")
    await fs.put(path)
    chunks = command.await_args_list[-2].args[0]["documents"]
    file = command.await_args_list[-1].args[0]["documents"][0]
    assert chunks[0]["data"] == Binary(b"payload")
    assert file["filename"] == "payload.bin"
    await fs.put("привет")
    assert command.await_args_list[-2].args[0]["documents"][0]["data"] == (
        Binary("привет".encode())
    )
    with pytest.raises(IncorrectGridFSData):
        await fs.put(123)  # pyright: ignore[reportArgumentType]


async def test_gridfs_accepts_binary_stream_and_rewinds_it() -> None:
    database = Kover(pool=MagicMock(spec=ConnectionPool)).get_database("test")
    command = AsyncMock(return_value={"ok": 1})
    database.command = command
    fs = GridFS(database)
    stream = BytesIO(b"payload")
    stream.read(3)
    await fs.put(stream)
    assert command.await_args_list[-2].args[0]["documents"][0]["data"] == (
        Binary(b"payload")
    )
