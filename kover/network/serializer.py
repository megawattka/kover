from __future__ import annotations

import os
import struct
from typing import TYPE_CHECKING, Any, Literal

from ..bson import (
    DEFAULT_CODEC_OPTIONS,
    _decode_all_selective,
    _make_c_string,
    encode,
)
from ..network import get_context_by_id

if TYPE_CHECKING:
    from collections.abc import Mapping

    from ..typings import xJsonT


class Serializer:
    """Serializer for MongoDB messages."""

    @staticmethod
    def _randint() -> int:  # request_id must be any integer
        return int.from_bytes(os.urandom(4), "big", signed=True)

    def _pack_message(
        self,
        op: int,
        message: bytes,
    ) -> tuple[int, bytes]:
        # https://www.mongodb.com/docs/manual/reference/mongodb-wire-protocol/#standard-message-header
        rid = self._randint()
        header = struct.pack("<iiii",
            16 + len(message),  # length including header
            rid,  # request ID
            0,  # response to
            op,  # op_code
        )
        return rid, header + message

    @staticmethod
    def _query_impl(
        doc: xJsonT,
        collection: str = "admin",
    ) -> bytes:
        # https://www.mongodb.com/docs/manual/legacy-opcodes/#op_query
        encoded = encode(
            doc,
            check_keys=False,
            codec_options=DEFAULT_CODEC_OPTIONS,
        )
        return b"".join([
            struct.pack("<i", 0),  # flags
            _make_c_string(f"{collection}.$cmd"),
            struct.pack("<i", 0),  # to_skip
            struct.pack("<i", -1),  # to_return (all)
            encoded,  # doc itself
        ])

    @staticmethod
    def _op_msg_impl(
        command: Mapping[str, Any],
        flags: int = 0,
    ) -> bytes:
        # https://www.mongodb.com/docs/manual/reference/mongodb-wire-protocol/#op_msg
        # https://www.mongodb.com/docs/manual/reference/mongodb-wire-protocol/#kind-0--body
        encoded = encode(
            command,
            check_keys=False,
            codec_options=DEFAULT_CODEC_OPTIONS,
        )
        return b"".join([
            struct.pack("<i", flags),
            struct.pack("<B", 0),  # section id 0 is single bson object
            encoded,  # doc itself
        ])

    @staticmethod
    def _get_compressor_id(
        compressor: Literal["zlib", "zstd", "snappy"],
    ) -> int:
        return {"snappy": 1, "zlib": 2, "zstd": 3}[compressor]

    def get_reply(  # noqa: D102
        self,
        msg: bytes,
        op_code: int,
    ) -> xJsonT:
        if op_code == 1:  # manual/legacy-opcodes/#op_reply
            # flags, cursor, starting, docs = struct.unpack_from("<iqii", msg)
            message = msg[20:]
        elif op_code == 2013:  # manual/reference/mongodb-wire-protocol/#op_msg
            # flags, section = struct.unpack_from("<IB", msg)
            message = msg[5:]
        elif op_code == 2012:
            # manual/reference/mongodb-wire-protocol/#op_compressed
            op_code, _, compressor_id = struct.unpack_from("<iiB", msg)
            ctx = get_context_by_id(compressor_id=compressor_id)
            message = ctx.decompress(msg[9:])  # skip fileds above
            return self.get_reply(message, op_code=op_code)
        else:
            raise AssertionError(f"Unsupported op_code from server: {op_code}")
        return _decode_all_selective(
            message,
            codec_options=DEFAULT_CODEC_OPTIONS,
            fields=None,
        )[0]

    def get_message(  # noqa: D102
        self,
        doc: xJsonT,
        compressor: Literal["zlib", "zstd", "snappy"] | None = None,
    ) -> tuple[int, bytes]:
        op_msg_m = self._op_msg_impl(doc)
        if compressor is None:
            return self._pack_message(
                2013,  # OP_MSG 2013
                self._op_msg_impl(doc),
            )
        compressor_id = self._get_compressor_id(compressor)
        ctx = get_context_by_id(compressor_id=compressor_id)
        compressed = ctx.compress(op_msg_m)

        rid = self._randint()
        header = struct.pack("<iiiiiiB",
            25 + len(compressed),  # message length
            rid,  # request ID
            0,  # response to
            2012,  # OP_COMPRESSED
            2013,  # OP_MSG
            len(op_msg_m),  # uncompressed length
            compressor_id,
        )
        return rid, header + compressed

    @staticmethod
    def verify_rid(  # noqa: D102
        data: bytes,
        rid: int,
    ) -> tuple[int, int]:
        # https://www.mongodb.com/docs/manual/reference/mongodb-wire-protocol/#standard-message-header
        length, _, response_to, op_code = struct.unpack("<iiii", data)
        if response_to != rid:
            exc_t = f"wrong r_id. expected ({rid}) but found ({response_to})"
            raise AssertionError(exc_t)
        return length, op_code
