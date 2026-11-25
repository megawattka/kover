from __future__ import annotations

import asyncio
from hashlib import sha1
from io import BytesIO, StringIO
import logging
import os
from pathlib import Path
from tempfile import TemporaryDirectory
from typing import TYPE_CHECKING, override

import pytest

from kover.gridfs import GridFS
from kover.gridfs.exceptions import GridFSFileNotFound, IncorrectGridFSData
from kover.gridfs.upload import MAX_CHUNK_SIZE
from kover.models import Delete
from tests.integration.base import MongoTestCase

if TYPE_CHECKING:
    from collections.abc import AsyncIterator

log = logging.getLogger(__name__)
logging.basicConfig(level=logging.INFO)


class GridFSIntegrationTests(MongoTestCase):
    def __init__(self, *args: str) -> None:
        self._9_mb = 1 * 1024 * 1024 * 9
        super().__init__(*args)

    async def test_gridfs(self) -> None:
        fs = await GridFS(self.database).indexed()
        payload = os.urandom(self._9_mb)
        file_id = await fs.put(payload)
        file, binary = await fs.get_by_file_id(file_id)
        assert file.metadata["sha1"] == sha1(payload).hexdigest()
        assert len(binary.getvalue()) == self._9_mb

    async def test_large_file_roundtrip_and_delete(self) -> None:
        fs = await GridFS(self.database).indexed()
        data = b"gridfs-test-" * (18 * 1024 * 1024 // 12 + 1)
        file_id = await fs.put(data, filename="large.bin")

        file, binary = await fs.get_by_file_id(file_id)
        assert binary.getvalue() == data
        assert file.length == len(data)
        assert file.metadata["sha1"] == sha1(data).hexdigest()

        assert await fs.exists(file_id)
        by_name, _ = await fs.get_by_filename("large.bin")
        assert by_name.object_id == file_id
        assert len(await fs.list()) == 1
        assert await fs.delete(file_id)

        assert not await fs.exists(file_id)
        chunks = self.database.get_collection("fs.chunks")
        assert await chunks.count() == 0
        assert not await fs.delete(file_id)

        with pytest.raises(GridFSFileNotFound):
            await fs.get_by_file_id(file_id)

    async def test_download_stream_reads_chunks_without_buffering_file(
        self,
    ) -> None:
        fs = await GridFS(self.database).indexed()
        data = b"0123456789" * 1000
        file_id = await fs.put(data, chunk_size=257)

        file, stream = await fs.open_download_stream(file_id)
        chunks = [chunk async for chunk in stream]

        assert file.length == len(data)
        assert all(len(chunk) <= 257 for chunk in chunks)
        assert b"".join(chunks) == data

    async def test_download_stream_resizes_output_blocks(self) -> None:
        fs = await GridFS(self.database).indexed()
        data = b"0123456789abcdefg"
        stored_size = 5
        file_id = await fs.put(data, chunk_size=stored_size)

        for size in (1, 3, stored_size, 8, len(data), len(data) + 1):
            file, download = await fs.open_download_stream(
                file_id, chunk_size=size,
            )
            assert file.chunk_size == stored_size
            async with download:
                blocks = [block async for block in download]
            assert blocks == [
                data[start : start + size]
                for start in range(0, len(data), size)
            ]

        empty_id = await fs.put(b"")
        _, download = await fs.open_download_stream(empty_id, chunk_size=8)
        async with download:
            assert [block async for block in download] == []

    async def test_resized_download_still_checks_sha1(self) -> None:
        fs = await GridFS(self.database).indexed()
        file_id = await fs.put(
            b"abcdef", chunk_size=3, metadata={"sha1": "invalid"},
        )
        _, download = await fs.open_download_stream(file_id, chunk_size=2)
        async with download:
            assert await anext(download) == b"ab"
            assert await anext(download) == b"cd"
            assert await anext(download) == b"ef"
            with pytest.raises(RuntimeError, match="sha1 hash mismatch"):
                await anext(download)

    async def test_put_stream_writes_before_exhausting_source(self) -> None:
        fs = await GridFS(self.database).indexed()
        chunks = self.database.get_collection("fs.chunks")
        data = b"a" * 65_537 + b"xyz"

        async def source() -> AsyncIterator[bytes]:
            yield b""
            yield data[:65_537]
            assert await chunks.count() > 0
            assert await fs.list() == []
            yield data[65_537:]

        file_id = await fs.put(source(), chunk_size=1024)
        file, download = await fs.open_download_stream(file_id)
        async with download:
            blocks = [block async for block in download]
        assert file.length == len(data)
        assert file.metadata["sha1"] == sha1(data).hexdigest()
        assert blocks == [
            data[i : i + 1024] for i in range(0, len(data), 1024)
        ]

    async def test_explicit_upload_and_early_download_close(self) -> None:
        fs = await GridFS(self.database).indexed()
        async with fs.open_upload_stream("stream.bin", chunk_size=3) as upload:
            await upload.write(b"a")
            await upload.write(b"bcdefgh" * 100)
            assert not await fs.exists(upload.file_id)
        await upload.close()
        with pytest.raises(ValueError, match="closed"):
            await upload.write(b"extra")

        file, download = await fs.open_download_stream(upload.file_id)
        assert file.filename == "stream.bin"
        async with download:
            assert await anext(download) == b"abc"
        with pytest.raises(StopAsyncIteration):
            await anext(download)

    async def test_put_aborts_when_source_raises(self) -> None:
        fs = await GridFS(self.database).indexed()
        chunks = self.database.get_collection("fs.chunks")

        async def source() -> AsyncIterator[bytes]:
            yield b"a" * 65_536
            assert await chunks.count() > 0
            msg = "producer stopped"
            raise RuntimeError(msg)

        with pytest.raises(RuntimeError, match="producer stopped"):
            await fs.put(source(), chunk_size=1024)
        assert await chunks.count() == 0
        assert await fs.list() == []

    async def test_put_aborts_on_cancellation(self) -> None:
        fs = await GridFS(self.database).indexed()
        chunks = self.database.get_collection("fs.chunks")
        paused = asyncio.Event()
        resume = asyncio.Event()

        async def source() -> AsyncIterator[bytes]:
            yield b"a" * 65_536
            paused.set()
            await resume.wait()

        task = asyncio.create_task(fs.put(source(), chunk_size=1024))
        try:
            await asyncio.wait_for(paused.wait(), timeout=5)
            assert await chunks.count() > 0
        finally:
            task.cancel()
            with pytest.raises(asyncio.CancelledError):
                await task
        assert await chunks.count() == 0
        assert await fs.list() == []

    async def test_explicit_abort_discards_written_chunks(self) -> None:
        fs = await GridFS(self.database).indexed()
        chunks = self.database.get_collection("fs.chunks")
        async with fs.open_upload_stream(chunk_size=1024) as upload:
            await upload.write(b"a" * 65_537)
            assert await chunks.count() > 0
            await upload.abort()
            await upload.abort()
        assert await chunks.count() == 0
        assert not await fs.exists(upload.file_id)

    async def test_put_supports_file_and_text_sources(self) -> None:
        fs = await GridFS(self.database).indexed()
        payload = b"gridfs" * 100_000
        with TemporaryDirectory() as directory:
            path = Path(directory) / "payload.bin"
            path.write_bytes(payload)
            path_id = await fs.put(path)
        file, content = await fs.get_by_file_id(path_id)
        assert file.filename == "payload.bin"
        assert content.read() == payload

        class NonSeekableSource(BytesIO):
            @override
            def seekable(self) -> bool:
                return False

            @override
            def tell(self) -> int:
                raise AssertionError

            @override
            def read(self, size: int | None = -1) -> bytes:
                assert size is not None
                assert size > 0
                return super().read(min(size, 47))

        with NonSeekableSource(payload[:1000]) as source:
            file_id = await fs.put(source, chunk_size=64, add_sha1=False)
            assert not source.closed
        file, content = await fs.get_by_file_id(file_id)
        assert file.metadata == {}
        assert content.read() == payload[:1000]

        text = "тест" * 80_000
        with StringIO(text) as source:
            source.seek(10)
            text_id = await fs.put(source, encoding="utf-16")
        _, content = await fs.get_by_file_id(text_id)
        assert content.read() == text.encode("utf-16")

    async def test_empty_stream_upload(self) -> None:
        fs = await GridFS(self.database).indexed()
        async with fs.open_upload_stream() as upload:
            await upload.write(b"")
        file, data = await fs.get_by_file_id(upload.file_id)
        assert file.length == 0
        assert data.read() == b""
        assert await self.database.get_collection("fs.chunks").count() == 0

    async def test_download_detects_missing_chunk_without_sha1(self) -> None:
        fs = await GridFS(self.database).indexed()
        file_id = await fs.put(b"abcde", chunk_size=3, add_sha1=False)
        chunks = self.database.get_collection("fs.chunks")
        await chunks.delete(Delete({"files_id": file_id, "n": 1}, limit=1))
        _, download = await fs.open_download_stream(file_id, check_sha1=False)
        async with download:
            assert await anext(download) == b"abc"
            with pytest.raises(IncorrectGridFSData, match="Missing GridFS"):
                await anext(download)

    async def test_rejects_invalid_chunk_sizes(self) -> None:
        fs = GridFS(self.database)
        for size in (0, -1, True, MAX_CHUNK_SIZE + 1):
            with pytest.raises(ValueError, match="chunk_size"):
                fs.open_upload_stream(chunk_size=size)

    async def test_max_chunk_size_fits_bson_insert(self) -> None:
        fs = await GridFS(self.database).indexed()
        block = b"a" * MAX_CHUNK_SIZE
        async with fs.open_upload_stream(chunk_size=MAX_CHUNK_SIZE) as upload:
            await upload.write(block)
            await upload.write(b"tail")
        file, download = await fs.open_download_stream(upload.file_id)
        assert file.length == len(block) + 4
        async with download:
            assert await anext(download) == block
            assert await anext(download) == b"tail"
            with pytest.raises(StopAsyncIteration):
                await anext(download)
