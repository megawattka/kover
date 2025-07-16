from __future__ import annotations

import os
import struct
from typing import TYPE_CHECKING, Any

import bson
from bson import DEFAULT_CODEC_OPTIONS

if TYPE_CHECKING:
    from collections.abc import Mapping

    from .typings import xJsonT


class Serializer:
    """Serializer for MongoDB messages."""

    @staticmethod
    def _randint() -> int:  # request_id must be any integer
        return int.from_bytes(os.urandom(4), "big", signed=True)

    @staticmethod
    def _to_bytes_le(num: int, size: int, signed: bool = True) -> bytes:
        return num.to_bytes(size, "little", signed=signed)

    def _pack_message(
        self,
        op: int,
        message: bytes,
    ) -> tuple[int, bytes]:
        # https://www.mongodb.com/docs/manual/reference/mongodb-wire-protocol/#standard-message-header
        rid = self._randint()
        packed = b"".join(self._to_bytes_le(x, size=4) for x in [
            16 + len(message),  # length
            rid,  # request_id
            0,  # response to set to 0
            op,
        ]) + message  # doc itself
        return rid, packed

    def _query_impl(
        self,
        doc: xJsonT,
        collection: str = "admin",
    ) -> bytes:
        # https://www.mongodb.com/docs/manual/legacy-opcodes/#op_query
        encoded = bson.encode(
            doc,
            check_keys=False,
            codec_options=DEFAULT_CODEC_OPTIONS,
        )
        return b"".join([
            self._to_bytes_le(0, size=4),  # flags
            bson._make_c_string(f"{collection}.$cmd"),  # type: ignore
            self._to_bytes_le(0, size=4),  # to_skip
            self._to_bytes_le(-1, size=4),  # to_return (all)
            encoded,  # doc itself
        ])

    def _op_msg_impl(
        self,
        command: Mapping[str, Any],
        flags: int = 0,
    ) -> bytes:
        # https://www.mongodb.com/docs/manual/reference/mongodb-wire-protocol/#op_msg
        # https://www.mongodb.com/docs/manual/reference/mongodb-wire-protocol/#kind-0--body
        encoded = bson.encode(
            command,
            check_keys=False,
            codec_options=DEFAULT_CODEC_OPTIONS,
        )
        section = self._to_bytes_le(0, size=1, signed=False)
        return b"".join([
            self._to_bytes_le(flags, size=4),
            section,  # section id 0 is single bson object
            encoded,  # doc itself
        ])

    @staticmethod
    def get_reply(  # noqa: D102
        msg: bytes,
        op_code: int,
    ) -> xJsonT:
        if op_code == 1:  # manual/legacy-opcodes/#op_reply
            # size 20
            # flags, cursor, starting, docs = struct.unpack_from("<iqii", msg)
            message = msg[20:]
        elif op_code == 2013:  # manual/reference/mongodb-wire-protocol/#op_msg
            # size 5
            # flags, section = struct.unpack_from("<IB", msg)
            message = msg[5:]
        else:
            raise AssertionError(f"Unsupported op_code from server: {op_code}")
        return bson._decode_all_selective(  # type: ignore
            message,
            codec_options=DEFAULT_CODEC_OPTIONS,
            fields=None,
        )[0]

    def get_message(  # noqa: D102
        self,
        doc: xJsonT,
    ) -> tuple[int, bytes]:
        return self._pack_message(
            2013,  # OP_MSG 2013
            self._op_msg_impl(doc),
        )

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
