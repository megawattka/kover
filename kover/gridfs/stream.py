"""Streaming downloads from GridFS."""

from __future__ import annotations

from hashlib import sha1
from typing import TYPE_CHECKING, Any, Self

if TYPE_CHECKING:
    from ..cursor import Cursor


class GridFSDownloadStream:
    """Read a GridFS file one chunk at a time."""

    def __init__(
        self,
        cursor: Cursor[dict[str, Any]],
        stored_sha1: str | None,
        *,
        check_sha1: bool,
    ) -> None:
        self._cursor = cursor
        self._stored_sha1 = stored_sha1 if check_sha1 else None
        self._digest = sha1()
        self._closed = False
        self._checked = False

    def __aiter__(self) -> Self:
        return self

    async def __anext__(self) -> bytes:
        if self._closed:
            raise StopAsyncIteration
        try:
            chunk = await self._cursor.__anext__()
        except StopAsyncIteration:
            await self._finish()
            raise

        except BaseException:
            await self.aclose()
            raise

        data = bytes(chunk["data"])
        self._digest.update(data)
        return data

    async def _finish(self) -> None:
        if self._checked:
            return

        self._checked = True
        await self.aclose()
        if (
            self._stored_sha1 is not None
            and self._stored_sha1 != self._digest.hexdigest()
        ):
            msg = "sha1 hash mismatch"
            raise RuntimeError(msg)

    async def aclose(self) -> None:
        """Close the underlying MongoDB cursor."""
        if not self._closed:
            self._closed = True
            await self._cursor.close()
