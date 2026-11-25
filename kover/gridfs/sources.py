"""Bounded reads from GridFS upload sources."""

from __future__ import annotations

from asyncio import to_thread
from codecs import getincrementalencoder
from collections.abc import AsyncIterable
from pathlib import Path
from threading import Lock
from typing import TYPE_CHECKING, Final

from .exceptions import IncorrectGridFSData

if TYPE_CHECKING:
    from collections.abc import AsyncGenerator, Generator
    from typing import BinaryIO, TextIO

    from .annotations import GridFSPayloadT

_READ_SIZE: Final = 256 * 1024


def _path_blocks(path: Path) -> Generator[bytes]:
    with path.open("rb") as source:
        while block := source.read(_READ_SIZE):
            yield block


def _rewind(source: BinaryIO | TextIO) -> None:
    if source.seekable() and source.tell() != 0:
        source.seek(0)


def _read(source: BinaryIO | TextIO) -> object:
    return source.read(_READ_SIZE)


async def _file_blocks(
    source: BinaryIO | TextIO,
    encoding: str,
) -> AsyncGenerator[bytes]:
    await to_thread(_rewind, source)
    encoder = None
    while True:
        block = await to_thread(_read, source)
        if isinstance(block, str):
            if encoder is None:
                encoder = getincrementalencoder(encoding)(errors="strict")
            yield encoder.encode(block, final=not block)
        elif isinstance(block, bytes):
            if block:
                yield block
        else:
            msg = "GridFS file reads must return bytes or str"
            raise IncorrectGridFSData(msg)
        if not block:
            return


async def _async_path_blocks(path: Path) -> AsyncGenerator[bytes]:
    blocks = _path_blocks(path)
    lock = Lock()

    def read() -> bytes:
        with lock:
            return next(blocks, b"")

    def close() -> None:
        # A cancelled to_thread can still be reading in its worker.
        with lock:
            blocks.close()

    try:
        while block := await to_thread(read):
            yield block
    finally:
        await to_thread(close)


def _local_blocks(
    source: Path | BinaryIO | TextIO,
    encoding: str,
) -> AsyncGenerator[bytes]:
    if isinstance(source, Path):
        return _async_path_blocks(source)

    if callable(getattr(source, "read", None)):
        return _file_blocks(source, encoding)

    msg = f"Unsupported GridFS upload source: {type(source).__name__}"
    raise IncorrectGridFSData(msg)


async def read_blocks(
    source: GridFSPayloadT,
    encoding: str,
) -> AsyncGenerator[bytes]:
    """Yield input blocks without reading the full file into memory."""
    if isinstance(source, bytes):
        yield source

    elif isinstance(source, str):
        encoder = getincrementalencoder(encoding)(errors="strict")
        for start in range(0, len(source), _READ_SIZE):
            yield encoder.encode(source[start : start + _READ_SIZE])
        yield encoder.encode("", final=True)

    elif isinstance(source, AsyncIterable):
        async for block in source:
            yield block
    else:
        blocks = _local_blocks(source, encoding)
        try:
            async for block in blocks:
                yield block
        finally:
            await blocks.aclose()
