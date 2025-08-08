from __future__ import annotations

from functools import lru_cache
import importlib.util
from typing import TYPE_CHECKING, Literal
import zlib

from pydantic import BaseModel, Field

if TYPE_CHECKING:
    from types import ModuleType

    from ..typings import CompressionContext

zstd = importlib.util.find_spec("zstd")
_HAVE_ZSTD = zstd is not None

snappy = importlib.util.find_spec("snappy")
_HAVE_SNAPPY = snappy is not None


@lru_cache
def _get_module(name: Literal["zstd", "snappy"]) -> ModuleType:
    return importlib.import_module(name)


class _ZlibContext(BaseModel):
    """Zlib compression context."""

    level: int = Field(ge=-1, le=9, default=-1)

    def compress(self, payload: bytes) -> bytes:
        return zlib.compress(payload, level=self.level)

    def decompress(self, payload: bytes) -> bytes:
        return zlib.decompress(payload)


class _ZstdContext(BaseModel):
    """ZStandart compression context."""

    def compress(self, payload: bytes) -> bytes:
        return _get_module("zstd").compress(payload)

    def decompress(self, payload: bytes) -> bytes:
        return _get_module("zstd").decompress(payload)


class _SnappyContext(BaseModel):
    """SnapPy compression context."""

    def compress(self, payload: bytes) -> bytes:
        return _get_module("snappy").compress(payload)

    def decompress(self, payload: bytes) -> bytes:
        return _get_module("snappy").decompress(payload)


@lru_cache
def get_context_by_id(compressor_id: int) -> CompressionContext:
    """Get the compression context by the compressor id."""
    compressors = {
        1: (_SnappyContext, _HAVE_SNAPPY, "Snappy"),
        2: (_ZlibContext, True, ""),
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
