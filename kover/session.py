from __future__ import annotations

import time
from enum import Enum
from typing import TYPE_CHECKING, Optional, Type
from types import TracebackType

from bson import Int64

from .typings import xJsonT, Self

if TYPE_CHECKING:
    from .client import MongoSocket


class TxnState(Enum):
    NONE = "NONE"
    STARTED = "STARTED"
    ABORTED = "ABORTED"
    COMMITED = "COMMITED"


class Transaction:
    def __init__(
        self,
        socket: MongoSocket,
        session_document: xJsonT
    ) -> None:
        self.socket: MongoSocket = socket
        self.session_document: xJsonT = session_document
        self.id: Int64 = Int64(-1)
        self.state: TxnState = TxnState.NONE
        self.action_count: int = 0
        self.exception: Optional[BaseException] = None

    @property
    def is_active(self) -> bool:
        return self.state is TxnState.STARTED

    @property
    def is_ended(self) -> bool:
        return self.state in (TxnState.COMMITED, TxnState.ABORTED)

    def start(self) -> None:
        timestamp = int(time.time())
        self.state = TxnState.STARTED
        self.id = Int64(timestamp)

    def end(
        self,
        state: TxnState,
        exc_value: Optional[BaseException]
    ) -> None:
        if not self.is_ended:
            self.state = state
            self.exception = exc_value

    async def commit(self) -> None:
        if not self.is_active:
            return
        command: xJsonT = {
            "commitTransaction": 1.0,
            "lsid": self.session_document,
            'txnNumber': self.id,
            'autocommit': False
        }
        await self.socket.request(command)

    async def abort(self) -> None:
        if not self.is_active:
            return
        command: xJsonT = {
            "abortTransaction": 1.0,
            "lsid": self.session_document,
            'txnNumber': self.id,
            'autocommit': False
        }
        await self.socket.request(command)

    async def __aenter__(self) -> Self:
        if not self.is_active:
            if self.is_ended:
                raise Exception("Cannot use transaction context twice")
            self.start()
            return self
        raise Exception("Transaction already used")

    async def __aexit__(
        self,
        exc_type: Optional[Type[BaseException]],
        exc_value: Optional[BaseException],
        exc_trace: Optional[TracebackType]
    ) -> bool:
        state = [TxnState.ABORTED, TxnState.COMMITED][exc_type is None]
        if self.action_count != 0:
            func = {
                TxnState.ABORTED: self.abort,
                TxnState.COMMITED: self.commit
            }[state]
            await func()
        self.end(state=state, exc_value=exc_value)
        return True

    def apply_to(self, command: xJsonT) -> None:
        if self.action_count == 0:
            command["startTransaction"] = True
        command.update({
            "txnNumber": self.id,
            "autocommit": False,
            "lsid": self.session_document
        })


class Session:
    def __init__(self, document: xJsonT, socket: MongoSocket) -> None:
        self.document: xJsonT = document
        self.socket: MongoSocket = socket

    def start_transaction(self) -> Transaction:
        return Transaction(
            socket=self.socket,
            session_document=self.document
        )

    def __repr__(self) -> str:
        return f"Session({self.document})"
