"""Internal protocols for kover."""

from typing import Any, Protocol, runtime_checkable


@runtime_checkable
class HasToDict(Protocol):
    """Protocol for objects that can be converted to a dictionary."""

    def to_dict(self) -> dict[str, Any]:
        """Serialize object into dict."""
        ...


class CompressionContext(Protocol):
    """Base Protocol for all compression contexts."""

    def compress(self, payload: bytes) -> bytes:
        """Compress payload."""
        ...

    def decompress(self, payload: bytes) -> bytes:
        """Decompress payload."""
        ...
