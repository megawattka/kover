from __future__ import annotations

from typing import TYPE_CHECKING

from .helpers import classrepr
from .transaction import Transaction

if TYPE_CHECKING:
    from .client import MongoTransport
    from .typings import xJsonT


@classrepr("document")
class Session:
    """Represents a MongoDB session.

    Attributes:
        document : The session document associated with the session.
        transport : The transport used to communicate with MongoDB.
    """

    def __init__(self, document: xJsonT, transport: MongoTransport) -> None:
        self.document: xJsonT = document
        self.transport = transport

    def start_transaction(self) -> Transaction:
        """Start a new transaction for this session."""
        return Transaction(
            transport=self.transport,
            session_document=self.document,
        )
