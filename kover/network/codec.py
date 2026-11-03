"""MongoDB OP_MSG command codec."""

from __future__ import annotations

import struct
from typing import TYPE_CHECKING, Any, Final, Literal

from bson import decode, encode  # pyright: ignore[reportUnknownVariableType]
from bson.codec_options import CodecOptions, TypeRegistry

from .compressors import get_context_by_id
from .type_codecs import BytesToBinaryDecoder

if TYPE_CHECKING:
    from collections.abc import Mapping

    from ..typings import DictT

OP_MSG: Final[int] = 2013
OP_COMPRESSED: Final[int] = 2012

# https://www.mongodb.com/docs/manual/reference/mongodb-wire-protocol/#standard-message-header
_MESSAGE_HEADER: Final[struct.Struct] = struct.Struct("<iiii")

# https://www.mongodb.com/docs/manual/reference/mongodb-wire-protocol/#op_msg
_MSG_BODY_HEADER: Final[struct.Struct] = struct.Struct("<iB")

# https://www.mongodb.com/docs/manual/reference/mongodb-wire-protocol/#op_compressed
_COMPRESSION_HEADER: Final[struct.Struct] = struct.Struct("<iiB")


class CommandCodec:
    """Encode OP_MSG commands and decode complete wire responses.

    Compression is optional and negotiated by the connection. Socket I/O,
    request ID generation and MongoDB command errors are handled elsewhere.
    """

    def __init__(
        self,
        compressor: Literal["zlib", "snappy", "zstd"] | None = None,
    ) -> None:
        self._codec_options: CodecOptions[DictT] = CodecOptions(
            type_registry=TypeRegistry(type_codecs=[BytesToBinaryDecoder()]),
        )
        self._compressor = compressor

    def set_compressor(
        self,
        compressor: Literal["zlib", "snappy", "zstd"] | None,
    ) -> None:
        """Set compression negotiated by hello."""
        self._compressor = compressor

    def _get_compressor_id(self) -> int:
        if self._compressor is None:
            raise RuntimeError("Cannot retrieve compressor id")

        ids = {"snappy": 1, "zlib": 2, "zstd": 3}
        return ids[self._compressor]

    def encode(
        self,
        command: Mapping[str, Any],
        database: str,
        *,
        request_id: int,
    ) -> bytes:
        """Build an OP_MSG command, optionally wrapped in OP_COMPRESSED.

        Args:
            command: Command fields to copy into a single kind-0 BSON body.
            database: Target database, overriding any existing $db field.
            request_id: Identifier used to correlate the server response.

        Returns:
            The complete wire message, including its standard header. The
            input command is not mutated.
        """
        document = {**command, "$db": database}  # order important
        # https://www.mongodb.com/docs/manual/reference/mongodb-wire-protocol/#kind-0--body
        body_header = _MSG_BODY_HEADER.pack(
            0,  # flags
            0,  # kind-0 section: a single BSON command document
        )
        body = body_header + encode(
            document,
            check_keys=False,
            codec_options=self._codec_options,
        )

        if self._compressor is None:
            payload = body
            opcode = OP_MSG
        else:
            compressor_id = {
                "snappy": 1,
                "zlib": 2,
                "zstd": 3,
            }[self._compressor]
            compressed = get_context_by_id(compressor_id).compress(body)
            compression_header = _COMPRESSION_HEADER.pack(
                OP_MSG,  # originalOpcode
                len(body),  # uncompressedSize, excluding the standard header
                compressor_id,
            )
            payload = compression_header + compressed
            opcode = OP_COMPRESSED

        header = _MESSAGE_HEADER.pack(
            _MESSAGE_HEADER.size + len(payload),  # messageLength
            request_id,  # requestID
            0,  # responseTo: this message initiates a request
            opcode,
        )
        return header + payload

    def decode(self, message: bytes, *, expected_response_to: int) -> DictT:
        """Validate response framing and decode a kind-0 BSON body.

        Accept an OP_MSG response or one wrapped in OP_COMPRESSED. The
        response must contain a single kind-0 body; document sequences and
        checksummed responses are not supported.

        Args:
            message: Complete wire response, including its standard header.
            expected_response_to: Request ID the response must refer to.

        Returns:
            The decoded response document, preserving BSON binary values.

        Raises:
            ValueError: If the header is truncated, the message length or
                response ID differs, or the OP_MSG body is unsupported.

        BSON decoding and decompression errors propagate to the caller.
        """
        if len(message) < _MESSAGE_HEADER.size:
            raise ValueError("MongoDB response is shorter than its header")

        length, _, response_to, opcode = _MESSAGE_HEADER.unpack_from(message)
        if length != len(message):
            raise ValueError(
                "MongoDB response length does not match its payload",
            )
        if response_to != expected_response_to:
            raise ValueError(
                f"wrong response id: expected {expected_response_to}, "
                f"got {response_to}",
            )

        payload = message[_MESSAGE_HEADER.size :]
        if opcode == OP_COMPRESSED:
            if len(payload) < _COMPRESSION_HEADER.size:
                raise ValueError("compressed response is truncated")

            inner_opcode, _, compressor_id = _COMPRESSION_HEADER.unpack_from(
                payload,
            )
            context = get_context_by_id(compressor_id)
            payload = context.decompress(payload[_COMPRESSION_HEADER.size :])
            opcode = inner_opcode

        if opcode != OP_MSG or len(payload) < _MSG_BODY_HEADER.size:
            raise ValueError("unsupported or invalid OP_MSG response")

        _, section_kind = _MSG_BODY_HEADER.unpack_from(payload)
        if section_kind != 0:
            raise ValueError("unsupported or invalid OP_MSG response")

        return decode(  # pyright: ignore[reportUnknownVariableType]
            payload[_MSG_BODY_HEADER.size :],
            codec_options=self._codec_options,
        )
