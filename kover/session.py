"""Logical client sessions and transaction state."""

from __future__ import annotations

from typing import TYPE_CHECKING, Any

from elune import Int64

from .exceptions import OperationFailure
from .models.tx_state import TxnState

if TYPE_CHECKING:
    from .client import Kover
    from .models.address import Address


class Session:
    """A logical MongoDB session that owns no socket."""

    def __init__(self, document: dict[str, Any], client: Kover) -> None:
        self.document = document
        self.client = client
        self._transaction_number = Int64(-1)
        self._state = TxnState.NONE
        self._transaction_options: dict[str, Any] | None = None
        self._pinned_server: Address | None = None

    def __repr__(self) -> str:
        session_id = self.document["id"]
        return f"Session(id={session_id.hex()}, tx_id={self.tx_id})"

    @property
    def tx_id(self) -> Int64:
        """Latest transaction number."""
        return self._transaction_number

    @property
    def state(self) -> TxnState:
        """The transaction state."""
        return self._state

    @property
    def in_transaction(self) -> bool:
        """Whether this session is inside a transaction."""
        return self._state in {TxnState.STARTING, TxnState.IN_PROGRESS}

    @property
    def pinned_server_address(self) -> Address | None:
        """Pinned server address."""
        return self._pinned_server

    def pin_server(self, address: Address) -> None:
        """Pin a server address without pinning a connection.

        Raises:
            ValueError: if session already pinned to another server.
        """
        if self._pinned_server is not None and self._pinned_server != address:
            raise ValueError("session is already pinned to another server")

        self._pinned_server = address

    def unpin_server(self) -> None:
        """Remove the server pin."""
        self._pinned_server = None

    def start_transaction(self, options: dict[str, Any] | None = None) -> None:
        """Start locally, without checking out a connection.

        A session supports one active transaction at a time, but can start
        another after commit or abort. Each new transaction receives a larger
        txnNumber; subsequent commands and commit retries retain that number.

        Args:
            options: Transaction options document reserved for future use.
                Currently stored locally, not applied to commands.

        Raises:
            ValueError: if transaction already has been started.
        """
        if self.in_transaction or self._state is TxnState.COMMITTING:
            raise ValueError("Session already has an active transaction")

        self._transaction_number = Int64(self._transaction_number + 1)
        self._transaction_options = options
        self._state = TxnState.STARTING

    async def commit_transaction(
        self,
        *,
        deadline: float | None = None,
    ) -> None:
        """Commit the active transaction without advancing its number.

        A transaction still in STARTING finishes locally without a command.

        Raises:
            ValueError: If the session has no active transaction.
            OperationFailure: Reraised from .request.
        """
        if self._state is TxnState.COMMITTED:
            return

        if self._state is TxnState.STARTING:
            self._state = TxnState.COMMITTED
            self.unpin_server()
            return

        if self._state not in {
            TxnState.IN_PROGRESS,
            TxnState.COMMITTING,
        }:
            raise ValueError("session has no active transaction")

        self._state = TxnState.COMMITTING
        try:
            await self.client.command(
                {
                    "commitTransaction": 1.0,
                },
                session=self,
                deadline=deadline,
            )
        except OperationFailure as e:
            if not e.is_unknown_commit_result:
                self._state = TxnState.ABORTED
                self.unpin_server()
            raise
        else:
            self._state = TxnState.COMMITTED
            self.unpin_server()

    async def abort_transaction(
        self,
        *,
        deadline: float | None = None,
    ) -> None:
        """Abort the active transaction and release its server pin.

        A transaction still in STARTING finishes locally without a command.

        Raises:
            ValueError: If the session has no active transaction.
            OperationFailure: If MongoDB rejects the abort with an error
                other than NoSuchTransaction.
        """
        if self._state is TxnState.ABORTED:
            return

        if self._state is TxnState.STARTING:
            self._state = TxnState.ABORTED
            self.unpin_server()
            return

        if self._state not in {
            TxnState.IN_PROGRESS,
            TxnState.COMMITTING,
        }:
            raise ValueError("session has no active transaction")

        try:
            await self.client.command(
                {"abortTransaction": 1.0},
                session=self,
                deadline=deadline,
            )
        except OperationFailure as e:
            # A failed write may have already aborted the transaction.
            # 251 corresponds to NoSuchTransaction
            if e.code != 251:  # ruff: ignore[magic-value-comparison]
                raise

        finally:
            self._state = TxnState.ABORTED
            self.unpin_server()

    def apply_to(self, document: dict[str, Any]) -> bool:
        """Add session and transaction metadata to a command.

        Returns:
            Whether this command starts the transaction.
        """
        document["lsid"] = self.document
        if self._state not in {
            TxnState.STARTING,
            TxnState.IN_PROGRESS,
            TxnState.COMMITTING,
        }:
            return False

        starts_transaction = self._state is TxnState.STARTING
        if starts_transaction:
            document["startTransaction"] = True
            document.update(
                {
                    "txnNumber": self._transaction_number,
                    "autocommit": False,
                },
            )
            return True

        document.update(
            {
                "txnNumber": self._transaction_number,
                "autocommit": False,
            },
        )
        return False

    def mark_transaction_started(self) -> None:
        """Record that the server accepted the first transaction command."""
        if self._state is TxnState.STARTING:
            self._state = TxnState.IN_PROGRESS

    async def close(self) -> None:
        """Close the session and clear transaction metadata."""
        if self.in_transaction or self._state is TxnState.COMMITTING:
            await self.abort_transaction()

        self.unpin_server()
