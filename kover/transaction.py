"""Transaction implementation for Kover."""

from __future__ import annotations

from typing import TYPE_CHECKING, Self

from .enums import TxnState
from .helpers import classrepr

if TYPE_CHECKING:
    from types import TracebackType

    from bson import Int64

    from .client import Kover
    from .typings import JsonT


@classrepr("tx_id", "state", "session_document")
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
        session_document: JsonT,
        transaction_number: Int64,
    ) -> None:
        self.client = client
        self.session_document: JsonT = session_document
        self.tx_id: Int64 = transaction_number
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
        return self.state in {TxnState.COMMITTED, TxnState.ABORTED}

    def start(self) -> None:
        """Start the transaction."""
        self.state = TxnState.STARTED

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

        await self.client.request({
            "commitTransaction": 1.0,
            "lsid": self.session_document,
            "txnNumber": self.tx_id,
            "autocommit": False,
        })
        self.end(TxnState.COMMITTED)

    async def abort(self) -> None:
        """Abort the transaction."""
        if not self.is_active:
            return

        await self.client.request({
            "abortTransaction": 1.0,
            "lsid": self.session_document,
            "txnNumber": self.tx_id,
            "autocommit": False,
        })
        self.end(TxnState.ABORTED)

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
        state = [TxnState.ABORTED, TxnState.COMMITTED][exc_type is None]
        if self.action_count != 0:
            state_func = {
                TxnState.ABORTED: self.abort,
                TxnState.COMMITTED: self.commit,
            }[state]
            await state_func()
        self.end(state=state, exc_value=exc_value)
        return False

    def apply_to(self, document: JsonT) -> None:
        """Apply transaction information to a MongoDB document."""
        if self.action_count == 0:
            document["startTransaction"] = True

        document.update({
            "txnNumber": self.tx_id,
            "autocommit": False,
            "lsid": self.session_document,
        })
