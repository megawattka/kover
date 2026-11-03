from __future__ import annotations

import asyncio
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from kover.network.transport import Transport


@pytest.mark.parametrize("method", ["exchange", "exchange_without_reply"])
@pytest.mark.parametrize("use_deadline", [True, False])
@pytest.mark.parametrize(
    "error_type",
    [OSError, RuntimeError, asyncio.CancelledError, BaseException],
)
async def test_incomplete_exchange_aborts_and_preserves_failure(
    method: str, error_type: type[BaseException], *, use_deadline: bool,
) -> None:
    transport = Transport("127.0.0.1", 27017)
    writer = MagicMock(spec=asyncio.StreamWriter)
    writer.is_closing.return_value = False
    error = error_type("exchange interrupted")
    writer.drain.side_effect = error
    reader = AsyncMock(spec=asyncio.StreamReader)
    deadline = (
        asyncio.get_running_loop().time() + 1 if use_deadline else None
    )
    with (
        patch.object(transport, "_writer", writer),
        patch.object(transport, "_reader", reader),
        patch.object(transport, "abort", wraps=transport.abort) as abort,
    ):
        with pytest.raises(error_type) as caught:
            await getattr(transport, method)(b"request", deadline=deadline)
        assert caught.value is error
        abort.assert_called_once()
        writer.close.assert_called_once()
        reader.readexactly.assert_not_awaited()
