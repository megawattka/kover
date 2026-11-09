"""Compression algorithms for network layer."""

from __future__ import annotations

from functools import lru_cache
import importlib.util
from typing import TYPE_CHECKING, Final, Literal
import zlib

from pydantic import BaseModel, Field

if TYPE_CHECKING:
    from types import ModuleType

    from ..._utils.protocols import CompressionContext


zstd = importlib.util.find_spec("zstd")
_HAVE_ZSTD = zstd is not None

snappy = importlib.util.find_spec("snappy")
_HAVE_SNAPPY = snappy is not None

ZLIB_COMPRESSOR_ID: Final[int] = 2


@lru_cache
def _get_module(name: Literal["zstd", "snappy"]) -> ModuleType:
    return importlib.import_module(name)


class _ZlibContext(BaseModel):
    """Zlib compression context."""

    level: int = Field(ge=-1, le=9, default=-1)

    def compress(self, payload: bytes) -> bytes:
        return zlib.compress(payload, level=self.level)

    @staticmethod
    def decompress(payload: bytes) -> bytes:
        return zlib.decompress(payload)


class _ZstdContext(BaseModel):
    """ZStandart compression context."""

    @staticmethod
    def compress(payload: bytes) -> bytes:
        return _get_module("zstd").compress(payload)

    @staticmethod
    def decompress(payload: bytes) -> bytes:
        return _get_module("zstd").decompress(payload)


class _SnappyContext(BaseModel):
    """SnapPy compression context."""

    @staticmethod
    def compress(payload: bytes) -> bytes:
        return _get_module("snappy").compress(payload)

    @staticmethod
    def decompress(payload: bytes) -> bytes:
        return _get_module("snappy").decompress(payload)


@lru_cache
def get_context_by_id(
    compressor_id: int,
    *,
    zlib_compression_level: int = -1,
) -> CompressionContext:
    """Get the compression context by the compressor id.

    Returns:
        An instance of the requested compression context.

    Raises:
        ModuleNotFoundError: If the requested compression module
            is not available.
    """
    if compressor_id == ZLIB_COMPRESSOR_ID:
        return _ZlibContext(level=zlib_compression_level)

    compressors = {
        1: (_SnappyContext, _HAVE_SNAPPY, "Snappy"),
        3: (_ZstdContext, _HAVE_ZSTD, "Zstd"),
    }
    ctx, available, module = compressors[compressor_id]
    if not available:
        raise ModuleNotFoundError(
            f"{module} compression cannot be used. "
            f"{module} is missing. "
            f"Install it via kover[{module.lower()}]",
        )
    return ctx()
