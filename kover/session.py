from __future__ import annotations

from enum import Enum
import time
from typing import TYPE_CHECKING

from bson import Int64
from typing_extensions import Self

if TYPE_CHECKING:
    from types import TracebackType

    from .client import MongoSocket
    from .typings import xJsonT


class TxnState(Enum):
    """Transaction states for MongoDB transactions."""
    NONE = "NONE"
    STARTED = "STARTED"
    ABORTED = "ABORTED"
    COMMITED = "COMMITED"


class Transaction:
    """Represents a MongoDB transaction.

    Attributes:
    ----------
    socket : MongoSocket
        The socket used to communicate with MongoDB.
    session_document : xJsonT
        The session document associated with the transaction.
    id : Int64
        The transaction identifier.
    state : TxnState
        The current state of the transaction.
    action_count : int
        The number of actions performed in the transaction.
    exception : BaseException | None
        The exception raised during the transaction, if any.

    Methods:
    -------
    start() -> None
        Starts the transaction.
    end(state: TxnState, exc_value: Optional[BaseException]) -> None
        Ends the transaction with the given state and exception.
    commit() -> None
        Commits the transaction.
    abort() -> None
        Aborts the transaction.
    apply_to(command: xJsonT) -> None
        Applies transaction information to a MongoDB command.
    """

    def __init__(
        self,
        socket: MongoSocket,
        session_document: xJsonT,
    ) -> None:
        self.socket: MongoSocket = socket
        self.session_document: xJsonT = session_document
        self.id: Int64 = Int64(-1)
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
        await self.socket.request(command)

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
        await self.socket.request(command)

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


class Session:
    """Represents a MongoDB session.

    Attributes:
    ----------
    document : xJsonT
        The session document associated with the session.
    socket : MongoSocket
        The socket used to communicate with MongoDB.

    Methods:
    -------
    start_transaction() -> Transaction
        Starts a new transaction for this session.
    """

    def __init__(self, document: xJsonT, socket: MongoSocket) -> None:
        self.document: xJsonT = document
        self.socket: MongoSocket = socket

    def start_transaction(self) -> Transaction:
        """Start a new transaction for this session."""  # noqa: DOC201
        return Transaction(
            socket=self.socket,
            session_document=self.document,
        )

    def __repr__(self) -> str:
        return f"Session({self.document})"
