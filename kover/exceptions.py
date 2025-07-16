from __future__ import annotations

from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from .typings import xJsonT


class OperationFailure(Exception):
    """General operation failure."""

    def __init__(self, code: int, message: xJsonT) -> None:
        self.code = code
        self.message = message


class SchemaGenerationException(Exception):
    """Raised when schema generation fails."""


class CorruptedDocument(Exception):
    """Raised when a document is corrupted or does not match the schema."""

    def __init__(self, missing_field: str) -> None:
        super().__init__(
            "Schema was updated but document in collection is not. "
            f'Missing field is: "{missing_field}"',
        )


class CredentialsException(Exception):
    """Raised when credentials are missing or invalid upon client creation."""

    def __init__(self) -> None:
        super().__init__(
            "either MONGO_PASSWORD or MONGO_USER environment "
            "variable is missing.",
        )


class UnsupportedAnnotation(Exception):
    """Raised when an unsupported annotation is encountered."""

    def __init__(self, annotation: object) -> None:
        super().__init__(f"Unsupported annotation: {annotation}")
