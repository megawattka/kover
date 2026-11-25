from __future__ import annotations

from unittest.mock import AsyncMock, MagicMock

import pytest

from kover.gridfs import GridFSUploadStream, IncorrectGridFSData
from kover.models import Delete


@pytest.fixture
def upload() -> tuple[GridFSUploadStream, AsyncMock, AsyncMock, AsyncMock]:
    files = MagicMock()
    files.insert_one = AsyncMock()
    chunks = MagicMock()
    chunks.insert_many = AsyncMock()
    chunks.delete = AsyncMock()
    stream = GridFSUploadStream(
        files, chunks, filename="file", chunk_size=1, add_sha1=True,
        metadata=None,
    )
    return stream, files.insert_one, chunks.insert_many, chunks.delete


async def test_failed_chunk_insert_preserves_error_without_cleanup(
    upload: tuple[GridFSUploadStream, AsyncMock, AsyncMock, AsyncMock],
) -> None:
    stream, publish, insert, delete = upload
    insert.side_effect = [None, RuntimeError("write failed")]
    with pytest.raises(RuntimeError, match="write failed"):
        async with stream:
            await stream.write(b"a" * 128)

    assert insert.await_count == 2
    publish.assert_not_awaited()
    delete.assert_not_awaited()
    with pytest.raises(ValueError, match="closed"):
        await stream.write(b"retry")


async def test_failed_publish_does_not_remove_chunks(
    upload: tuple[GridFSUploadStream, AsyncMock, AsyncMock, AsyncMock],
) -> None:
    stream, publish, insert, delete = upload
    publish.side_effect = RuntimeError("publish failed")
    with pytest.raises(RuntimeError, match="publish failed"):
        async with stream:
            await stream.write(b"abc")

    insert.assert_awaited_once()
    publish.assert_awaited_once()
    delete.assert_not_awaited()


async def test_source_error_is_preserved_when_abort_fails(
    upload: tuple[GridFSUploadStream, AsyncMock, AsyncMock, AsyncMock],
) -> None:
    stream, publish, _, delete = upload
    delete.side_effect = RuntimeError("delete failed")

    async def upload_then_fail() -> None:
        async with stream:
            await stream.write(b"a" * 64)
            msg = "source failed"
            raise RuntimeError(msg)

    with pytest.raises(RuntimeError, match="source failed") as failure:
        await upload_then_fail()

    publish.assert_not_awaited()
    delete.assert_awaited_once_with(Delete(
        {"files_id": {"$eq": stream.file_id}}, limit=0,
    ))
    assert "delete failed" in failure.value.__notes__[0]


async def test_invalid_upload_block_aborts_and_closes_stream(
    upload: tuple[GridFSUploadStream, AsyncMock, AsyncMock, AsyncMock],
) -> None:
    stream, publish, _, delete = upload
    await stream.write(b"a" * 64)
    with pytest.raises(IncorrectGridFSData, match="must be bytes"):
        await stream.write("not bytes")  # pyright: ignore[reportArgumentType]
    delete.assert_awaited_once()
    await stream.close()
    publish.assert_not_awaited()
