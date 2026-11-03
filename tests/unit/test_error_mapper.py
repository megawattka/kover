from __future__ import annotations

from typing import TYPE_CHECKING
from unittest.mock import AsyncMock, patch

import pytest

from kover.exceptions import OperationFailure
from kover.models.network import Address
from kover.network.codec import CommandCodec
from kover.network.connection import Connection
from kover.network.error_mapper import ErrorMapper
from kover.network.transport import Transport

if TYPE_CHECKING:
    from kover.typings import DictT


@pytest.mark.parametrize(("reply", "code"), [
    ({"ok": 0, "code": 59, "errmsg": "Unknown command"}, 59),
    ({"ok": 1, "writeErrors": [
        {"code": 121, "errmsg": "Validation failed"},
    ]}, 121),
    ({"ok": 1, "writeConcernError": {
        "code": 64, "errmsg": "Write concern failed",
    }}, 64),
])
async def test_connection_raises_server_errors_without_abort(
    reply: DictT, code: int,
) -> None:
    transport = Transport("127.0.0.1", 27017)
    codec = CommandCodec()
    connection = Connection(
        Address(host="127.0.0.1", port=27017),
        transport, codec, ErrorMapper())
    with (
        patch.object(
            transport, "exchange", new=AsyncMock(return_value=b"reply"),
        ),
        patch.object(codec, "decode", return_value=reply),
        patch.object(transport, "abort") as abort,
    ):
        with pytest.raises(OperationFailure) as caught:
            await connection.command({"insert": "items"})
        assert caught.value.code == code
        assert caught.value.details == reply
        abort.assert_not_called()


async def test_nested_metadata_and_labels_are_merged() -> None:
    reply: DictT = {
        "ok": 1,
        "errorLabels": ["RetryableWriteError", "shared"],
        "writeErrors": [{
            "code": 121,
            "codeName": "DocumentValidationFailure",
            "errmsg": "Invalid document",
            "errInfo": {"failingDocumentId": "invalid"},
            "errorLabels": ["TransientTransactionError", "shared"],
        }],
        "writeConcernError": {"code": 64, "errmsg": "Lower priority"},
    }
    error = await ErrorMapper().get_exception(reply)
    assert error.code == 121
    assert error.code_name == "DocumentValidationFailure"
    assert error.err_info == {"failingDocumentId": "invalid"}
    assert error.error_labels == frozenset({
        "RetryableWriteError", "TransientTransactionError", "shared",
    })
    assert error.details == reply
    assert error.details is not reply


async def test_write_concern_metadata_is_preserved() -> None:
    reply: DictT = {"ok": 1, "writeConcernError": {
        "code": 64, "errmsg": "Timed out", "errInfo": {"wtimeout": True},
        "errorLabels": ["UnknownTransactionCommitResult"],
    }}
    with pytest.raises(OperationFailure) as caught:
        await ErrorMapper().check_writes(reply)
    assert caught.value.code == 64
    assert caught.value.err_info == {"wtimeout": True}
    assert caught.value.is_unknown_commit_result


async def test_cached_exception_types_have_independent_metadata() -> None:
    mapper = ErrorMapper()
    first = await mapper.get_exception({
        "code": 2, "errmsg": "first", "errInfo": {"detail": "first"},
        "errorLabels": ["TransientTransactionError"],
    })
    second = await mapper.get_exception({
        "code": 2, "errmsg": "second", "errInfo": {"detail": "second"},
    })
    assert type(first) is type(second)
    assert first is not second
    assert first.err_info == {"detail": "first"}
    assert second.err_info == {"detail": "second"}
    assert first.is_transient_transaction_error
    assert not second.is_transient_transaction_error
    assert first.has_label("TransientTransactionError")
    assert first.labels == frozenset({"TransientTransactionError"})


async def test_missing_error_code_preserves_original_details() -> None:
    reply: DictT = {"ok": 0, "errmsg": "Failure without code"}
    error = await ErrorMapper().get_exception(reply)
    assert error.code == -1
    assert error.details == reply
    assert error.message == str(reply)
    assert error.err_info is None
