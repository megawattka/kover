"""Bounded-memory asynchronous uploads to GridFS."""

from __future__ import annotations

from asyncio import CancelledError, Lock
import datetime as dt
from hashlib import sha1
from typing import TYPE_CHECKING, Any, Final, Self

from elune import Binary, ObjectId

from ..models import Delete
from .exceptions import IncorrectGridFSData
from .models import Chunk, File

if TYPE_CHECKING:
    from types import TracebackType

    from ..collection import Collection

DEFAULT_CHUNK_SIZE: Final = 255 * 1024
# The driver packs inserts into one BSON command document. Leave room for
# the chunk document, its array key, and command and session fields.
MAX_CHUNK_SIZE: Final = 16 * 1024 * 1024 - 4096
_BATCH_BUDGET: Final = 8 * 1024 * 1024
_MAX_BATCH_CHUNKS: Final = 64


class GridFSUploadStream:
    """Write a GridFS file in bounded batches; publish it on close."""

    def __init__(  # ruff: ignore[too-many-arguments] -- Explicit upload options.
        self,
        files: Collection,
        chunks: Collection,
        *,
        filename: str | None,
        chunk_size: int,
        add_sha1: bool,
        metadata: dict[str, Any] | None,
    ) -> None:
        if (
            type(chunk_size) is not int
            or not 1 <= chunk_size <= MAX_CHUNK_SIZE
        ):
            msg = f"chunk_size must be an integer in [1, {MAX_CHUNK_SIZE}]"
            raise ValueError(msg)
        self._files = files
        self._chunks = chunks
        self._file_id = ObjectId()
        self._filename = filename
        self._chunk_size = chunk_size
        self._metadata = dict(metadata or {})
        self._digest = sha1() if add_sha1 else None
        self._batch_limit = max(
            1, min(_MAX_BATCH_CHUNKS, _BATCH_BUDGET // (chunk_size + 72)),
        )
        self._pending = bytearray()
        self._batch: list[Chunk] = []
        self._length = 0
        self._next_n = 0
        self._closed = False
        self._sent_chunks = False
        self._lock = Lock()

    @property
    def file_id(self) -> ObjectId:
        """ID of the file, available before it is published."""
        return self._file_id

    async def __aenter__(self) -> Self:
        return self

    async def __aexit__(
        self,
        exc_type: type[BaseException] | None,
        exc_value: BaseException | None,
        traceback: TracebackType | None,
    ) -> None:
        if exc_value is None:
            await self.close()
        else:
            async with self._lock:
                await self._abort_after_error(exc_value)

    async def write(self, data: bytes) -> None:
        """Accept a block of bytes, waiting for MongoDB when a batch fills.

        Raises:
            ValueError: The stream is already closed.
        """
        async with self._lock:
            if self._closed:
                msg = "GridFS upload stream is closed"
                raise ValueError(msg)
            try:
                await self._write_blocks(data)
            except BaseException as exc:
                await self._abort_after_error(exc)
                raise

    async def _write_blocks(self, data: object) -> None:
        if not isinstance(data, bytes):
            msg = "GridFS upload blocks must be bytes"
            raise IncorrectGridFSData(msg)
        view = memoryview(data)
        start = 0
        if self._pending:
            start = min(len(view), self._chunk_size - len(self._pending))
            self._pending.extend(view[:start])
            if len(self._pending) == self._chunk_size:
                await self._queue_chunk(bytes(self._pending))
                self._pending.clear()

        while len(view) - start >= self._chunk_size:
            end = start + self._chunk_size
            await self._queue_chunk(bytes(view[start:end]))
            start = end
        self._pending.extend(view[start:])

    async def _queue_chunk(self, data: bytes) -> None:
        if self._digest is not None:
            self._digest.update(data)
        self._length += len(data)
        self._batch.append(Chunk(
            files_id=self._file_id, n=self._next_n, data=Binary(data),
        ))
        self._next_n += 1
        if len(self._batch) == self._batch_limit:
            await self._flush()

    async def _flush(self) -> None:
        if not self._batch:
            return
        self._sent_chunks = True
        try:
            await self._chunks.insert_many(self._batch)
        except Exception:
            # GridFS does not attempt a delete after a failed server write.
            self._finish()
            raise
        self._batch.clear()

    def _finish(self) -> None:
        self._closed = True
        self._pending.clear()
        self._batch.clear()

    async def close(self) -> None:
        """Flush remaining bytes and publish the file once."""
        async with self._lock:
            if self._closed:
                return
            try:
                if self._pending:
                    await self._queue_chunk(bytes(self._pending))
                await self._flush()
                await self._publish()
            except BaseException as exc:
                await self._abort_after_error(exc)
                raise

    async def _publish(self) -> None:
        metadata = self._metadata.copy()
        if self._digest is not None:
            metadata.setdefault("sha1", self._digest.hexdigest())
        file = File(
            chunk_size=self._chunk_size,
            length=self._length,
            upload_date=dt.datetime.now(tz=dt.UTC),
            filename=self._filename,
            metadata=metadata,
        )
        file.object_id = self._file_id
        # The file might already be visible if the acknowledgement is lost.
        self._finish()
        await self._files.insert_one(file)

    async def abort(self) -> None:
        """Discard the upload and delete its written chunks if still open."""
        async with self._lock:
            await self._abort()

    async def _abort(self) -> None:
        if not self._closed:
            self._finish()
            if self._sent_chunks:
                await self._chunks.delete(Delete(
                    {"files_id": {"$eq": self._file_id}}, limit=0,
                ))

    async def _abort_after_error(self, error: BaseException) -> None:
        try:
            await self._abort()
        except (Exception, CancelledError) as exc:  # ruff: ignore[blind-except]
            error.add_note(f"GridFS upload cleanup also failed: {exc!r}")
