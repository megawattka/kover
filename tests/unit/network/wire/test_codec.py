from __future__ import annotations

import struct
from uuid import uuid4
import zlib

from bson import Binary, UuidRepresentation, decode, encode
from bson.codec_options import CodecOptions
import pytest

from kover.network.wire.codec import (
    OP_COMPRESSED,
    OP_MSG,
    CommandCodec,
)
from kover.network.wire.compression import get_context_by_id


def response(
    document: dict[str, object],
    *,
    request_id: int = 7,
    section_kind: int = 0,
) -> bytes:
    payload = struct.pack("<iB", 0, section_kind) + encode(document)
    header = struct.pack(
        "<iiii",
        16 + len(payload),
        9,
        request_id,
        OP_MSG,
    )
    return header + payload


def compressed_response(
    document: dict[str, object],
    *,
    request_id: int = 7,
) -> bytes:
    original = struct.pack("<iB", 0, 0) + encode(document)
    compressed = struct.pack("<iiB", OP_MSG, len(original), 2) + zlib.compress(
        original,
    )
    return (
        struct.pack(
            "<iiii",
            16 + len(compressed),
            9,
            request_id,
            OP_COMPRESSED,
        )
        + compressed
    )


def test_encode_op_msg_copies_input_and_overrides_database() -> None:
    codec = CommandCodec()
    command = {"ping": 1, "$db": "wrong", "nested": {"x": True}}
    wire = codec.encode(command, "admin", request_id=41)
    length, request_id, response_to, opcode = struct.unpack_from("<iiii", wire)
    assert length == len(wire)
    assert request_id == 41
    assert response_to == 0
    assert opcode == OP_MSG
    assert decode(wire[21:]) == {
        "ping": 1,
        "$db": "admin",
        "nested": {"x": True},
    }
    assert command["$db"] == "wrong"


@pytest.mark.parametrize("compressor", [None, "zlib"])
def test_codec_applies_uuid_options_on_encode_and_decode(
    compressor: str | None,
) -> None:
    options = CodecOptions(uuid_representation=UuidRepresentation.STANDARD)
    codec = CommandCodec(compressor, codec_options=options)
    value = uuid4()
    wire = codec.encode(
        {"insert": "items", "documents": [{"uuid": value}]},
        "shop",
        request_id=7,
    )
    body = wire[16:] if compressor is None else zlib.decompress(wire[25:])
    document = decode(body[5:], codec_options=options)
    assert document["documents"][0]["uuid"] == value

    make_response = response if compressor is None else compressed_response
    reply = make_response(
        {"ok": 1, "uuid": Binary.from_uuid(value)},
    )
    assert codec.decode(reply, request_id=7)["uuid"] == value


def test_default_codec_rejects_native_uuid() -> None:
    with pytest.raises(ValueError, match="UNSPECIFIED"):
        CommandCodec().encode(
            {"insert": "items", "uuid": uuid4()},
            "shop",
            request_id=7,
        )


def test_encode_and_decode_compressed_op_msg() -> None:
    codec = CommandCodec("zlib")
    command = {"find": "items"}
    wire = codec.encode(command, "shop", request_id=4)
    assert struct.unpack_from("<i", wire, 12)[0] == OP_COMPRESSED
    assert codec.decode(compressed_response({"ok": 1}), request_id=7) == {
        "ok": 1,
    }
    assert (
        codec.decode(response({"data": Binary(b"\x00\xff")}), request_id=7)[
            "data"
        ]
        == b"\x00\xff"
    )
    codec.set_compressor(None)
    assert codec.encode(command, "shop", request_id=5) != wire


@pytest.mark.parametrize("level", [-1, 0, 1, 9])
def test_codec_uses_configured_zlib_level_after_negotiation(
    level: int,
) -> None:
    codec = CommandCodec(zlib_compression_level=level)
    command = {"insert": "items", "data": "compressible" * 1000}
    uncompressed = codec.encode(command, "shop", request_id=4)
    codec.set_compressor("zlib")
    wire = codec.encode(command, "shop", request_id=4)
    assert struct.unpack_from("<i", wire, 12)[0] == OP_COMPRESSED
    assert wire[25:] == zlib.compress(uncompressed[16:], level=level)
    assert codec.decode(compressed_response({"ok": 1}), request_id=7) == {
        "ok": 1,
    }
    codec.set_compressor(None)
    codec.set_compressor("zlib")
    assert codec.encode(command, "shop", request_id=4) == wire


@pytest.mark.parametrize("level", [-2, 10])
def test_codec_rejects_invalid_zlib_level(level: int) -> None:
    with pytest.raises(ValueError, match="level"):
        CommandCodec(zlib_compression_level=level)


def test_zlib_context_cache_keeps_levels_separate() -> None:
    payload = b"compressible" * 1000
    uncompressed = get_context_by_id(2, zlib_compression_level=0)
    compressed = get_context_by_id(2, zlib_compression_level=9)
    assert uncompressed is get_context_by_id(2, zlib_compression_level=0)
    assert uncompressed is not compressed
    assert uncompressed.compress(payload) == zlib.compress(payload, level=0)
    assert compressed.compress(payload) == zlib.compress(payload, level=9)
    assert get_context_by_id(2).compress(payload) == zlib.compress(payload)


def test_codec_rejects_invalid_compressor_and_frames() -> None:
    codec = CommandCodec()
    with pytest.raises(RuntimeError, match="compressor id"):
        codec._get_compressor_id()  # pyright: ignore[reportPrivateUsage] # ruff: ignore[private-member-access]

    with pytest.raises(RuntimeError):
        codec.set_compressor("invalid")

    with pytest.raises(ValueError, match="exactly 16"):
        codec.message_length(b"short")

    with pytest.raises(ValueError, match="shorter than its header"):
        codec.message_length(struct.pack("<iiii", 15, 1, 0, OP_MSG))

    with pytest.raises(ValueError, match="exactly 4"):
        codec.frame_length(b"bad")

    with pytest.raises(ValueError, match="shorter than its header"):
        codec.frame_length(struct.pack("<i", 3))


@pytest.mark.parametrize(
    ("message", "request_id", "error"),
    [
        (b"short", 7, "shorter than its header"),
        (struct.pack("<iiii", 17, 1, 7, OP_MSG), 7, "length does not match"),
        (response({"ok": 1}, request_id=8), 7, "wrong response id"),
        (response({"ok": 1}, section_kind=1), 7, "unsupported"),
    ],
)
def test_decode_rejects_invalid_response_frames(
    message: bytes,
    request_id: int,
    error: str,
) -> None:
    with pytest.raises(ValueError, match=error):
        CommandCodec().decode(message, request_id=request_id)


def test_decode_rejects_short_compressed_header_and_invalid_opcodes() -> None:
    codec = CommandCodec()
    short_compressed_payload = b"1234"
    short_compressed = (
        struct.pack(
            "<iiii",
            20,
            1,
            7,
            OP_COMPRESSED,
        )
        + short_compressed_payload
    )
    with pytest.raises(ValueError, match="compressed response is truncated"):
        codec.decode(short_compressed, request_id=7)

    invalid = struct.pack("<iiii", 16, 1, 7, 42)
    with pytest.raises(ValueError, match="unsupported"):
        codec.decode(invalid, request_id=7)

    compressed_payload = struct.pack("<iiB", 42, 1, 2) + zlib.compress(b"x")
    compressed_bad_inner = (
        struct.pack(
            "<iiii",
            16 + len(compressed_payload),
            1,
            7,
            OP_COMPRESSED,
        )
        + compressed_payload
    )
    with pytest.raises(ValueError, match="unsupported"):
        codec.decode(compressed_bad_inner, request_id=7)
