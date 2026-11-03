from __future__ import annotations

import struct
from typing import TYPE_CHECKING, Literal

from bson import Binary
import pytest

from kover.helpers import get_hello_payload
from kover.network.codec import OP_COMPRESSED, OP_MSG, CommandCodec

if TYPE_CHECKING:
    from kover.typings import DictT


def response(
    document: DictT, compressor: Literal["zlib"] | None = None,
) -> bytes:
    message = bytearray(
        CommandCodec(compressor).encode(
            document,
            "admin",
            request_id=123,
        ),
    )
    struct.pack_into("<i", message, 8, 42)
    return bytes(message)


@pytest.mark.parametrize("compressor", [None, "zlib"])
def test_wire_roundtrip_and_header(compressor: Literal["zlib"] | None) -> None:
    original: DictT = {
        "ok": 1,
        "value": "compressible" * 100,
        "binary": b"data",
    }
    message = response(original, compressor)
    length, request_id, response_to, opcode = struct.unpack(
        "<iiii", message[:16],
    )
    assert (length, request_id, response_to) == (len(message), 123, 42)
    assert opcode == (OP_MSG if compressor is None else OP_COMPRESSED)
    decoded = CommandCodec().decode(message, expected_response_to=42)
    assert decoded["value"] == original["value"]
    assert decoded["binary"] == Binary(b"data")
    assert isinstance(decoded["binary"], Binary)


@pytest.mark.parametrize("length", [0, 1, 15])
def test_truncated_header_rejected(length: int) -> None:
    with pytest.raises(ValueError, match="shorter"):
        CommandCodec().decode(b"x" * length, expected_response_to=42)


@pytest.mark.parametrize(
    ("offset", "value", "match"),
    [
        (0, 17, "length"),
        (8, 43, "response id"),
        (12, 2004, "unsupported"),
    ],
)
def test_invalid_header_rejected(offset: int, value: int, match: str) -> None:
    message = bytearray(response({"ok": 1}))
    struct.pack_into("<i", message, offset, value)
    with pytest.raises(ValueError, match=match):
        CommandCodec().decode(bytes(message), expected_response_to=42)


def test_truncated_compression_header_and_invalid_section() -> None:
    message = struct.pack("<iiii", 20, 1, 42, OP_COMPRESSED) + b"1234"
    with pytest.raises(ValueError, match="truncated"):
        CommandCodec().decode(message, expected_response_to=42)
    invalid = bytearray(response({"ok": 1}))
    invalid[20] = 1
    with pytest.raises(ValueError, match="unsupported"):
        CommandCodec().decode(bytes(invalid), expected_response_to=42)


def test_compression_can_be_enabled_and_disabled() -> None:
    codec = CommandCodec()
    codec.set_compressor("zlib")
    assert (
        struct.unpack_from(
            "<i", codec.encode({"ping": 1}, "admin", request_id=1), 12,
        )[0]
        == OP_COMPRESSED
    )
    codec.set_compressor(None)
    assert (
        struct.unpack_from(
            "<i", codec.encode({"ping": 1}, "admin", request_id=2), 12,
        )[0]
        == OP_MSG
    )


def test_hello_metadata_and_application() -> None:
    payload = get_hello_payload(["zlib"], {"name": "test"})
    assert payload["hello"] == 1
    assert payload["compression"] == ["zlib"]
    assert payload["application"] == {"name": "test"}
    assert payload["client"]["driver"]["name"] == "Kover"
    assert payload["client"]["os"]["architecture"]
    assert "application" not in get_hello_payload()
