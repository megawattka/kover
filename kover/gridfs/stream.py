"""Streaming downloads from GridFS."""

from __future__ import annotations

from asyncio import CancelledError
from hashlib import sha1
from typing import TYPE_CHECKING, Any, Self

from elune import Binary

from .exceptions import IncorrectGridFSData

if TYPE_CHECKING:
    from types import TracebackType

    from ..cursor import Cursor
    from .models import File


class GridFSDownloadStream:
    """Read a GridFS file one chunk at a time."""

    def __init__(
        self,
        cursor: Cursor[dict[str, Any]],
        stored_sha1: str | None,
        *,
        check_sha1: bool,
        file: File | None = None,
        chunk_size: int | None = None,
    ) -> None:
        self._cursor = cursor
        self._stored_sha1 = stored_sha1 if check_sha1 else None
        self._digest = sha1() if self._stored_sha1 is not None else None
        self._chunk_size = file.chunk_size if file is not None else None
        self._output_size = chunk_size
        self._pending = b""
        self._offset = 0
        self._remaining = file.length if file is not None else 0
        self._next_n = 0
        self._closed = False

    async def __aenter__(self) -> Self:
        return self

    async def __aexit__(
        self,
        exc_type: type[BaseException] | None,
        exc_value: BaseException | None,
        traceback: TracebackType | None,
    ) -> None:
        if exc_value is None:
            await self.aclose()
        else:
            await self._close_after_error(exc_value)

    def __aiter__(self) -> Self:
        return self

    async def __anext__(self) -> bytes:
        if self._closed:
            raise StopAsyncIteration

        try:
            size = self._output_size
            data = (
                await self._read_chunk() if size is None
                else await self._read_block(size)
            )
        except BaseException as exc:
            await self._close_after_error(exc)
            raise

        if data is None:
            raise StopAsyncIteration

        return data

    async def _read_chunk(self) -> bytes | None:
        try:
            chunk = await anext(self._cursor)
        except StopAsyncIteration:
            await self._finish()
            return None

        data = self._decode_chunk(chunk)
        if self._digest is not None:
            self._digest.update(data)

        return data

    async def _read_block(self, size: int) -> bytes | None:
        block = bytearray()
        while len(block) < size:
            if self._offset == len(self._pending):
                data = await self._read_chunk()
                if data is None:
                    break
                self._pending = data
                self._offset = 0

            start = self._offset
            end = min(len(self._pending), start + size - len(block))
            self._offset = end
            if not block and end - start == size:
                return self._pending[start:end]

            block.extend(memoryview(self._pending)[start:end])
        return bytes(block) if block else None

    def _decode_chunk(self, chunk: dict[str, Any]) -> bytes:
        raw = chunk.get("data")
        if not isinstance(raw, (bytes, Binary)):
            msg = f"Invalid GridFS binary data at position {self._next_n}"
            raise IncorrectGridFSData(msg)

        data = bytes(raw)
        if self._chunk_size is not None:
            expected_size = min(self._remaining, self._chunk_size)
            if (
                expected_size <= 0
                or chunk.get("n") != self._next_n
                or len(data) != expected_size
            ):
                msg = f"Invalid GridFS chunk at position {self._next_n}"
                raise IncorrectGridFSData(msg)

            self._remaining -= len(data)
            self._next_n += 1
        return data

    async def _finish(self) -> None:
        await self.aclose()
        if self._remaining:
            msg = f"Missing GridFS chunk at position {self._next_n}"
            raise IncorrectGridFSData(msg)
        if (
            self._digest is not None
            and self._stored_sha1 != self._digest.hexdigest()
        ):
            msg = "sha1 hash mismatch"
            raise RuntimeError(msg)

    async def _close_after_error(self, error: BaseException) -> None:
        try:
            await self.aclose()
        except (Exception, CancelledError) as exc:  # ruff: ignore[blind-except]
            error.add_note(f"GridFS download cleanup also failed: {exc!r}")

    async def aclose(self) -> None:
        """Close the underlying MongoDB cursor."""
        if not self._closed:
            self._closed = True
            self._pending = b""
            await self._cursor.close()
