from __future__ import annotations

import asyncio
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from kover.exceptions import OperationFailure
from kover.network.connection import Connection
from kover.network.pool import ConnectionPool


class InterruptedRequest(BaseException):
    """An interruption outside the ordinary Exception hierarchy."""


@pytest.mark.parametrize("wait_response", [True, False])
async def test_request_releases_successful_connection(
    *, wait_response: bool,
) -> None:
    connection = MagicMock(spec=Connection)
    connection.usable = True
    connection.command.return_value = {"ok": 1}
    document = {"ping": 1}
    with patch.object(
        ConnectionPool, "_create_connection", return_value=connection,
    ):
        pool = ConnectionPool(max_pool_size=1)
        release = AsyncMock(wraps=pool.release)
        pool.release = release
        try:
            response = await pool.request(
                document, db_name="test", wait_response=wait_response,
                deadline=42,
            )
            assert response == ({"ok": 1} if wait_response else {})
            assert document == {"ping": 1}
            method = (
                connection.command if wait_response
                else connection.fire_and_forget
            )
            method.assert_awaited_once_with(
                document, "test", deadline=42,
            )
            unused = (
                connection.fire_and_forget if wait_response
                else connection.command
            )
            unused.assert_not_awaited()
            release.assert_awaited_once_with(connection, discard=False)
            connection.close.assert_not_awaited()
        finally:
            await pool.close()


@pytest.mark.parametrize("wait_response", [True, False])
@pytest.mark.parametrize("error_type", [
    RuntimeError, asyncio.CancelledError, InterruptedRequest, OperationFailure,
])
async def test_request_releases_connection_on_every_exit(
    error_type: type[BaseException], *, wait_response: bool,
) -> None:
    connection = MagicMock(spec=Connection)
    connection.usable = True
    error = (
        OperationFailure(13, "denied") if error_type is OperationFailure
        else error_type("interrupted")
    )
    method = (
        connection.command if wait_response else connection.fire_and_forget
    )
    method.side_effect = error
    with patch.object(
        ConnectionPool, "_create_connection", return_value=connection,
    ):
        pool = ConnectionPool(max_pool_size=1)
        release = AsyncMock(wraps=pool.release)
        pool.release = release
        try:
            with pytest.raises(error_type) as caught:
                await pool.request({"ping": 1}, wait_response=wait_response)
            assert caught.value is error
            release.assert_awaited_once_with(
                connection, discard=error_type is not OperationFailure,
            )
            if error_type is OperationFailure:
                connection.close.assert_not_awaited()
            else:
                connection.close.assert_awaited_once()
        finally:
            await pool.close()
