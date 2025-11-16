"""Kover Cursor Module."""

from __future__ import annotations

from collections import deque
from typing import (
    TYPE_CHECKING,
    Generic,
    TypeVar,
    cast,
)

from bson import Int64
from typing_extensions import Self

from .helpers import filter_non_null

if TYPE_CHECKING:
    from .collection import Collection
    from .models import Collation
    from .schema import Document
    from .session import Transaction
    from .typings import xJsonT

T = TypeVar("T")


class Cursor(Generic[T]):
    """Asynchronous MongoDB-like cursor for iterating over query results."""

    def __init__(
        self,
        filter_: xJsonT,
        collection: Collection,
        cls: type[Document] | None = None,
        transaction: Transaction | None = None,
    ) -> None:
        self._id: Int64 | None = None
        self._collection = collection
        self._limit = 0
        self._filter = filter_
        self._projection: xJsonT | None = None
        self._sort: xJsonT | None = None
        self._skip: int = 0
        self._limit: int = 0
        self._hint: str | xJsonT | None = None
        self._batch_size: int = 101
        self._comment: str | None = None
        self._retrieved: int = 0
        self._killed: bool = False
        self._second_iteration: bool = False
        self._docs: deque[T] = deque()
        self._cls = cls
        self._transaction = transaction
        self._collation: Collation | None = None

    async def __aenter__(self) -> Self:
        return self

    async def __aexit__(self, *args: object) -> None:
        await self.close()

    def sort(self, mapping: xJsonT) -> Self:
        """Set the sort order for the query results.

        Parameters:
            mapping : A mapping specifying the sort order for the query.

        Returns:
            The cursor instance with the sort order applied.
        """
        self._sort = mapping
        return self

    def skip(self, value: int) -> Self:
        """Set the skip amount for the query results.

        Parameters:
            value : Amount to skip.

        Returns:
            The cursor instance with the sort order applied.
        """
        self._skip = value
        return self

    def limit(self, value: int) -> Self:
        """Set the limit for the query.

        Parameters:
            value : Maximum amount of docs to return.

        Returns:
            The cursor instance with the sort order applied.
        """
        self._limit = value
        return self

    def batch_size(self, value: int) -> Self:
        """Set the batch size for the query results.

        Parameters:
            value : Maximum amount of docs to return from first batch.

        Returns:
            The cursor instance with the projection applied.
        """
        self._batch_size = value
        return self

    def projection(self, mapping: xJsonT) -> Self:
        """Set the projection for the query results.

        Parameters:
            mapping : A mapping specifying the fields
                to include or exclude in the query results.

        Returns:
            The cursor instance with the projection applied.
        """
        self._projection = mapping
        return self

    def comment(self, comment: str) -> Self:
        """Set the comment for operation.

        Parameters:
            comment : A comment that will be shown in logs.

        Returns:
            The cursor instance with the projection applied.
        """
        self._comment = comment
        return self

    def hint(self, hint: str | xJsonT) -> Self:
        """Set the hint for the query.

        Parameters:
            hint : Index hint to optimize query performance.

        Returns:
            The cursor instance with the hint applied.
        """
        self._hint = hint
        return self

    def _get_query(self) -> xJsonT:
        collation = self._collation.to_dict() if self._collation else None
        return filter_non_null({
            "find": self._collection.name,
            "filter": self._filter,
            "skip": self._skip,
            "limit": self._limit,
            "projection": self._projection,
            "sort": self._sort,
            "batchSize": self._batch_size,
            "comment": self._comment,
            "collation": collation,
            "hint": self._hint,
        })

    def _map_docs(
        self,
        documents: list[xJsonT],
    ) -> list[T]:
        if self._cls is not None:
            documents = [
                self._cls.from_document(doc) for doc in documents
            ]  # pyright: ignore[reportAssignmentType]
        return cast("list[T]", documents)

    def __aiter__(self) -> Self:
        return self

    async def __anext__(self) -> T:
        if self._docs:
            return self._docs.popleft()
        if self._id is None:
            query = self._get_query()
            request = await self._collection.database.command(
                query,
                transaction=self._transaction,
            )
            docs = request["cursor"]["firstBatch"]
            self._retrieved += len(docs)
            self._id = request["cursor"]["id"]
            self._docs.extend(self._map_docs(docs))
        else:
            if int(self._id) == 0 or self._second_iteration:
                await self.close()
                raise StopAsyncIteration

            self._second_iteration = True
            command: xJsonT = {
                "getMore": Int64(self._id),
                "collection": self._collection.name,
            }
            request = await self._collection.database.command(
                command,
                transaction=self._transaction,
            )
            docs = request["cursor"]["nextBatch"]
            self._retrieved += len(docs)
            self._docs.extend(self._map_docs(docs))

        if self._docs:
            return self._docs.popleft()

        raise StopAsyncIteration

    async def close(self) -> None:
        """Close the cursor and release any associated resources.

        This method kills the cursor on the server if it is still active and
        clears any remaining documents in the local buffer.
        """
        if not self._killed:
            self._killed = True
            if self._id is not None and int(self._id) > 0 and self._limit != 0:
                command: xJsonT = {
                    "killCursors": self._collection.name,
                    "cursors": [self._id],
                }
                await self._collection.database.command(command)
            self._docs.clear()

    async def to_list(self) -> list[T]:
        """Return all documents from the cursor as a list.

        Returns:
            A list containing all documents retrieved by the cursor.
        """
        return [doc async for doc in self]
