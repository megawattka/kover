"""Type codecs used in kover."""

from typing import override

from bson import Binary
from bson.codec_options import TypeDecoder

INT32_MAX = 2**31 - 1


class BytesToBinaryDecoder(TypeDecoder):
    """Represents bytes to binary decoder."""

    @override
    def transform_bson(self, value: bytes) -> Binary:
        """Convert bytes to binary.

        Returns:
            Converted binary.
        """
        return Binary(value, 0)

    @property
    def bson_type(self) -> type[bytes]:
        """Property, that indicates what type we are decoding."""
        return bytes
