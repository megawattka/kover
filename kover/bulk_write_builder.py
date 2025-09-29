"""Builder for kover BulkWrite operations."""

from __future__ import annotations

from typing import TYPE_CHECKING

from .helpers import filter_non_null

if TYPE_CHECKING:
    from .models import Delete, Update
    from .typings import xJsonT


# https://www.mongodb.com/docs/manual/reference/command/bulkWrite
class BulkWriteBuilder:
    """Builder for bulk write operations."""

    def __init__(
        self,
        *,
        ordered: bool = True,
        bypass_document_validation: bool = False,
        comment: str | None = None,
        let: xJsonT | None = None,
        errors_only: bool = False,
        cursor_batch_size: int | None = None,
        write_concern: str | int = "majority",
    ) -> None:
        self.ordered = ordered
        self.bypass_document_validation = bypass_document_validation
        self.comment = comment
        self.let = let
        self.errors_only = errors_only
        self.cursor = {"batchSize": cursor_batch_size or 101}
        self.write_concern = write_concern
        self._operations: list[xJsonT] = []
        self._namespaces: list[str] = []

    def _prepair_additional_params(self) -> xJsonT:
        return filter_non_null({
            "ordered": self.ordered,
            "bypassDocumentValidation": self.bypass_document_validation,
            "comment": self.comment,
            "let": self.let,
            "errorsOnly": self.errors_only,
            "cursor": self.cursor,
            "writeConcern": {"w": self.write_concern},
        })

    def _get_ns_idx(self, namespace: str) -> int:
        if namespace not in self._namespaces:
            self._namespaces.append(namespace)
        return self._namespaces.index(namespace)

    def add_insert(
        self,
        documents: list[xJsonT],
        /,
        *,
        ns: str,
    ) -> None:
        """Adds an Insert operations into the builder."""
        idx = self._get_ns_idx(ns)
        for document in documents:
            self._operations.append({"insert": idx, "document": document})

    def add_update(
        self,
        update: Update,
        ns: str,
    ) -> None:
        """Adds an Update operations into the builder."""
        idx = self._get_ns_idx(ns)
        self._operations.append({
            "update": idx,
            **update.as_bulk_write_op(),
        })

    def add_delete(
        self,
        delete: Delete,
        ns: str,
    ) -> None:
        """Adds an Delete operations into the builder."""
        idx = self._get_ns_idx(ns)
        self._operations.append({
            "delete": idx,
            **delete.as_bulk_write_op(),
        })

    def build(self) -> xJsonT:
        """Build the command.

        Returns:
            The command that was built for Kover.bulk_write method.
        """
        return {
            "bulkWrite": 1,
            "ops": self._operations,
            "nsInfo": [{"ns": ns} for ns in self._namespaces],
            **self._prepair_additional_params(),
        }
