"""Session Module for Kover."""

from __future__ import annotations

from typing import TYPE_CHECKING

from bson import Int64

from .helpers import classrepr
from .transaction import Transaction

if TYPE_CHECKING:
    from .client import Kover
    from .typings import JsonT


@classrepr("document")
class Session:
    """Represents a MongoDB session.

    Attributes:
        document : The session document associated with the session.
        client : The client used to communicate with MongoDB.
    """

    def __init__(self, document: JsonT, client: Kover) -> None:
        self.document: JsonT = document
        self.client = client
        self._transaction_number = Int64(-1)

    def start_transaction(self) -> Transaction:
        """Start a new transaction for this session.

        Returns:
            A new transaction object associated with this session
        """
        return Transaction(
            client=self.client,
            session_document=self.document,
            transaction_number=self._next_transaction_number(),
        )

    def _next_transaction_number(self) -> Int64:
        self._transaction_number = Int64(self._transaction_number + 1)
        return self._transaction_number
