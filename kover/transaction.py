"""Transaction implementation for Kover."""

from __future__ import annotations

import time
from typing import TYPE_CHECKING

from typing_extensions import Self

from .bson import Int64
from .enums import TxnState
from .helpers import classrepr

if TYPE_CHECKING:
    from types import TracebackType

    from .client import Kover
    from .typings import xJsonT


@classrepr("_id", "state", "session_document")
class Transaction:
    """Represents a MongoDB transaction.

    Attributes:
        client : The client used to communicate with MongoDB.
        session_document : The transaction's session document.
        id : The transaction identifier.
        state : The current state of the transaction.
        action_count : The number of actions performed in the transaction.
        exception : The exception raised during the transaction, if any.
    """

    def __init__(
        self,
        client: Kover,
        session_document: xJsonT,
    ) -> None:
        self.client = client
        self.session_document: xJsonT = session_document
        self._id: Int64 = Int64(-1)
        self.state: TxnState = TxnState.NONE
        self.action_count: int = 0
        self.exception: BaseException | None = None

    @property
    def is_active(self) -> bool:
        """Check if the transaction is active."""
        return self.state is TxnState.STARTED

    @property
    def is_ended(self) -> bool:
        """Check if the transaction has ended."""
        return self.state in {TxnState.COMMITED, TxnState.ABORTED}

    def start(self) -> None:
        """Start the transaction."""
        self.state = TxnState.STARTED
        self.id = Int64(int(time.time()))

    def end(
        self,
        state: TxnState,
        exc_value: BaseException | None = None,
    ) -> None:
        """End the transaction with the specified state and exception."""
        if not self.is_ended:
            self.state = state
            self.exception = exc_value

    async def commit(self) -> None:
        """Commit the transaction."""
        if not self.is_active:
            return
        command: xJsonT = {
            "commitTransaction": 1.0,
            "lsid": self.session_document,
            "txnNumber": self.id,
            "autocommit": False,
        }
        await self.client.request(command)

    async def abort(self) -> None:
        """Abort the transaction."""
        if not self.is_active:
            return
        command: xJsonT = {
            "abortTransaction": 1.0,
            "lsid": self.session_document,
            "txnNumber": self.id,
            "autocommit": False,
        }
        await self.client.request(command)

    async def __aenter__(self) -> Self:
        if not self.is_active:
            if self.is_ended:
                raise ValueError("Cannot use transaction context twice")
            self.start()
            return self
        raise ValueError("Transaction already used")

    async def __aexit__(
        self,
        exc_type: type[BaseException] | None,
        exc_value: BaseException | None,
        exc_traceback: TracebackType | None,
    ) -> bool:
        state = [TxnState.ABORTED, TxnState.COMMITED][exc_type is None]
        if self.action_count != 0:
            state_func = {
                TxnState.ABORTED: self.abort,
                TxnState.COMMITED: self.commit,
            }[state]
            await state_func()
        self.end(state=state, exc_value=exc_value)
        return True

    def apply_to(self, document: xJsonT) -> None:
        """Apply transaction information to a MongoDB document."""
        if self.action_count == 0:
            document["startTransaction"] = True

        document.update({
            "txnNumber": self.id,
            "autocommit": False,
            "lsid": self.session_document,
        })
