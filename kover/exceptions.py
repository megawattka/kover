"""Kover exception hierarchy."""

from __future__ import annotations

from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from .typings import DictT


class DriverError(Exception):
    """Base driver failure carrying MongoDB error labels."""

    def __init__(
        self,
        message: str,
        *,
        labels: frozenset[str] | None = None,
    ) -> None:
        super().__init__(message)
        if labels is None:
            labels = frozenset()

        self.error_labels = labels

    @property
    def labels(self) -> frozenset[str]:
        """MongoDB error labels."""
        return self.error_labels

    def has_label(self, label: str) -> bool:
        """Check a MongoDB error label.

        Returns:
            True if label in labels False otherwise.
        """
        return label in self.error_labels


class ConnectionClosedError(DriverError, ConnectionError):
    """A command attempted to use a closed connection."""


class NetworkError(DriverError, ConnectionError):
    """A socket exchange failed."""


class ProtocolError(DriverError, RuntimeError):
    """The server sent an invalid wire message."""


class PoolClosedError(DriverError, RuntimeError):
    """Checkout from a closed pool."""


class PoolPausedError(DriverError):
    """Checkout from a paused pool."""


class PoolTimeoutError(DriverError, TimeoutError):
    """The checkout deadline expired."""


class ServerSelectionError(DriverError, TimeoutError):
    """No suitable server was discovered before the selection deadline."""


class InvalidOperationError(DriverError, ValueError):
    """An operation is not permitted in the current state."""


class OperationFailure(DriverError):
    """General MongoDB command failure."""

    def __init__(
        self,
        code: int,
        message: str,
        *,
        labels: frozenset[str] | None = None,
    ) -> None:
        super().__init__(message, labels=labels)
        self.code = code
        self.message = message
        self.code_name: str | None = None
        self.details: DictT = {}
        self.err_info = None

    @property
    def is_transient_transaction_error(self) -> bool:
        """Whether the error permits retrying the whole transaction."""
        return self.has_label("TransientTransactionError")

    @property
    def is_unknown_commit_result(self) -> bool:
        """Whether the outcome of a commit is unknown."""
        return self.has_label("UnknownTransactionCommitResult")


class SchemaGenerationException(Exception):
    """Raised when schema generation fails."""


class CredentialsException(Exception):
    """Raised when credentials are missing or invalid upon client creation."""

    def __init__(self) -> None:
        super().__init__(
            "either MONGO_PASSWORD or MONGO_USER environment "
            "variable is missing.",
        )
