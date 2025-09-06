"""Session Module for Kover."""

from __future__ import annotations

from typing import TYPE_CHECKING

from .helpers import classrepr
from .transaction import Transaction

if TYPE_CHECKING:
    from .client import Kover
    from .typings import xJsonT


@classrepr("document")
class Session:
    """Represents a MongoDB session.

    Attributes:
        document : The session document associated with the session.
        transport : The transport used to communicate with MongoDB.
    """

    def __init__(self, document: xJsonT, client: Kover) -> None:
        self.document: xJsonT = document
        self.client = client

    def start_transaction(self) -> Transaction:
        """Start a new transaction for this session.

        Returns:
            A new transaction object associated with this session
        """
        return Transaction(
            client=self.client,
            session_document=self.document,
        )
