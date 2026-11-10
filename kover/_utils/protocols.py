"""Internal protocols for kover."""

from typing import Protocol


class CompressionContext(Protocol):
    """Base Protocol for all compression contexts."""

    def compress(self, payload: bytes) -> bytes:
        """Compress payload."""
        ...

    def decompress(self, payload: bytes) -> bytes:
        """Decompress payload."""
        ...
