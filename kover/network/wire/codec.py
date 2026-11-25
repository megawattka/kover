"""MongoDB OP_MSG command codec."""

from __future__ import annotations

import struct
from typing import TYPE_CHECKING, Any, Final, Literal, overload

from elune import decode, encode
from elune.codec_options import DEFAULT_CODEC_OPTIONS

from .compression import ZLIB_COMPRESSOR_ID, get_context_by_id

if TYPE_CHECKING:
    from collections.abc import Mapping

    from elune.codec_options import CodecOptions


OP_MSG: Final[int] = 2013
OP_COMPRESSED: Final[int] = 2012
EXHAUST_ALLOWED: Final[int] = 1 << 16
MORE_TO_COME: Final[int] = 1 << 1
MONGODB_MESSAGE_PREFIX_LEN: Final[int] = 4

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
        compressor: str | None = None,
        *,
        zlib_compression_level: int = -1,
        codec_options: CodecOptions | None = DEFAULT_CODEC_OPTIONS,
    ) -> None:
        self._codec_options = codec_options or DEFAULT_CODEC_OPTIONS
        self._compressor = compressor
        self._zlib_context = get_context_by_id(
            ZLIB_COMPRESSOR_ID,
            zlib_compression_level=zlib_compression_level,
        )

    def set_compressor(
        self,
        compressor: str | None,
    ) -> None:
        """Set compression negotiated by hello.

        Raises:
            RuntimeError: if compressor is unknown.
        """
        if compressor not in {"zlib", "zstd", "snappy", None}:
            msg = f"Unknown compressor: {compressor}"
            raise RuntimeError(msg)

        self._compressor = compressor

    def _get_compressor_id(self) -> int:
        if self._compressor is None:
            msg = "Cannot retrieve compressor id"
            raise RuntimeError(msg)

        ids = {"snappy": 1, "zlib": 2, "zstd": 3}
        return ids[self._compressor]

    def encode(
        self,
        command: Mapping[str, Any],
        database: str,
        *,
        request_id: int,
        flags: int = 0,
    ) -> bytes:
        """Build an OP_MSG command, optionally wrapped in OP_COMPRESSED.

        Args:
            command: Command fields to copy into a single kind-0 BSON body.
            database: Target database, overriding any existing $db field.
            request_id: Identifier used to correlate the server response.
            flags: OP_MSG flags, including ``exhaustAllowed`` when streaming.

        Returns:
            The complete wire message, including its standard header. The
            input command is not mutated.
        """
        document = {**command, "$db": database}  # order important

        # https://www.mongodb.com/docs/manual/reference/mongodb-wire-protocol/#kind-0--body
        body_header = _MSG_BODY_HEADER.pack(
            flags,
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
            context = (
                self._zlib_context
                if compressor_id == ZLIB_COMPRESSOR_ID
                else get_context_by_id(compressor_id)
            )
            compressed = context.compress(body)
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

    @staticmethod
    def message_length(header: bytes) -> int:
        """Unpacks and validates messge length.

        Returns:
            length unpacked.

        Raises:
            ValueError: if something went wrong.
        """
        if len(header) != _MESSAGE_HEADER.size:
            msg = "MongoDB message header must be exactly 16 bytes"
            raise ValueError(msg)

        length, _, _, _ = _MESSAGE_HEADER.unpack(header)
        if length < _MESSAGE_HEADER.size:
            msg = "MongoDB message is shorter than its header"
            raise ValueError(msg)

        return length

    @staticmethod
    def frame_length(prefix: bytes) -> int:
        """Unpack and validate the four-byte MongoDB frame prefix.

        Returns:
            frame length as integer.

        Raises:
            ValueError: if something went wrong.
        """
        if len(prefix) != MONGODB_MESSAGE_PREFIX_LEN:
            msg = "MongoDB message prefix must be exactly 4 bytes"
            raise ValueError(msg)

        length = struct.unpack("<i", prefix)[0]
        if length < _MESSAGE_HEADER.size:
            msg = "MongoDB message is shorter than its header"
            raise ValueError(msg)

        return length

    @overload
    def decode(
        self,
        message: bytes,
        *,
        request_id: int,
        exhaustive: Literal[True] = True,
    ) -> dict[str, Any]: ...

    @overload
    def decode(
        self,
        message: bytes,
        *,
        request_id: int,
        exhaustive: Literal[False],
    ) -> tuple[dict[str, Any], int, bool]: ...

    def decode(
        self,
        message: bytes,
        *,
        request_id: int,
        exhaustive: bool = True,
    ) -> dict[str, Any] | tuple[dict[str, Any], int, bool]:
        """Validate response framing and decode a kind-0 BSON body.

        Accept an OP_MSG response or one wrapped in OP_COMPRESSED. The
        response must contain a single kind-0 body; document sequences and
        checksummed responses are not supported.

        Args:
            message: Complete wire response, including its standard header.
            request_id: Request ID the response must refer to.
            exhaustive: If true, reject ``moreToCome`` responses and return
                only the document. If false, return the document, message ID,
                and ``moreToCome`` flag.

        Returns:
            The decoded response document, or response metadata when
            ``exhaustive`` is false.

        Raises:
            ValueError: If the header is truncated, the message length or
                response ID differs, or the OP_MSG body is unsupported.

        BSON decoding and decompression errors propagate to the caller.
        """
        document, message_id, more = self._decode(
            message,
            request_id=request_id,
        )
        if exhaustive is False:
            return document, message_id, more
        if more:
            msg = "unexpected OP_MSG moreToCome response"
            raise ValueError(msg)
        return document

    def _decode(
        self,
        message: bytes,
        *,
        request_id: int,
    ) -> tuple[dict[str, Any], int, bool]:
        """Decode a reply and streaming metadata.

        Returns:
            The document, message ID, and ``moreToCome`` flag.

        Raises:
            ValueError: If framing, response correlation, or flags are invalid.
        """
        if len(message) < _MESSAGE_HEADER.size:
            msg = "MongoDB response is shorter than its header"
            raise ValueError(msg)

        length, message_id, response_to, opcode = _MESSAGE_HEADER.unpack_from(
            message,
        )
        if length != len(message):
            msg = "MongoDB response length does not match its payload"
            raise ValueError(
                msg,
            )
        if response_to != request_id:
            msg = (
                f"wrong response id: expected {request_id}, got {response_to}"
            )
            raise ValueError(
                msg,
            )

        payload = message[_MESSAGE_HEADER.size :]
        if opcode == OP_COMPRESSED:
            if len(payload) < _COMPRESSION_HEADER.size:
                msg = "compressed response is truncated"
                raise ValueError(msg)

            inner_opcode, _, compressor_id = _COMPRESSION_HEADER.unpack_from(
                payload,
            )
            context = get_context_by_id(compressor_id)
            payload = context.decompress(payload[_COMPRESSION_HEADER.size :])
            opcode = inner_opcode

        if opcode != OP_MSG or len(payload) < _MSG_BODY_HEADER.size:
            msg = "unsupported or invalid OP_MSG response"
            raise ValueError(msg)

        flags, section_kind = _MSG_BODY_HEADER.unpack_from(payload)
        if section_kind != 0 or flags & (0xFFFF ^ MORE_TO_COME):
            msg = "unsupported or invalid OP_MSG response"
            raise ValueError(msg)

        document = decode(
            payload[_MSG_BODY_HEADER.size :],
            codec_options=self._codec_options,
        )
        return document, message_id, bool(flags & MORE_TO_COME)
