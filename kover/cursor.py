"""Asynchronous MongoDB cursor."""

from __future__ import annotations

from collections import deque
from typing import TYPE_CHECKING, Any, NoReturn, Self, cast

from elune import Int64

from ._utils.mappings import maybe_to_dict
from .execution.context import CommandReply

if TYPE_CHECKING:
    from collections.abc import Callable
    from types import TracebackType

    from .collection import Collection
    from .models.address import Address
    from .models.collation import Collation
    from .models.read_preference import ReadPreference
    from .session import Session


class Cursor[T]:
    """Lazy asynchronous cursor.

    Concurrent reads and closing during a read are not supported.
    """

    def __init__(
        self,
        query: dict[str, Any],
        collection: Collection,
        decoder: Callable[[dict[str, Any]], T],
        session: Session | None = None,
    ) -> None:
        self._decoder = decoder
        self._query = query.copy()
        self._collection = collection
        self._session = session
        self._server_address: Address | None = None
        self._read_preference: ReadPreference | None = None

        self._id: Int64 | None = None
        self._server_database = collection.database.name
        self._server_collection = collection.name
        self._docs: deque[T] = deque()

        self._started = False
        self._closed = False
        self._reading = False
        self._first: T | None = None
        self._first_cached = False

        self._options: dict[str, Any] = {}
        self._command_response: dict[str, Any] | None = None
        self._get_more_batch_size = 101

    async def __aenter__(self) -> Self:
        return self

    async def __aexit__(
        self,
        exc_type: type[BaseException] | None,
        exc_value: BaseException | None,
        traceback: TracebackType | None,
    ) -> None:
        if exc_value is None:
            await self.close()
        else:
            await self._close_after_error(exc_value)

    def __aiter__(self) -> Self:
        return self

    def _ensure_at_start(self) -> None:
        if self._started or self._closed:
            raise RuntimeError("Cursor is already started or closed")

    def _ensure_single_thread(self) -> None:
        if self._reading:
            raise RuntimeError("Concurrent use of cursor is not supported")

    def _set_option(self, name: str, value: object) -> Self:
        self._ensure_at_start()

        self._options[name] = value
        return self

    def sort(self, mapping: dict[str, Any]) -> Self:  # ruff: ignore[undocumented-public-method]
        return self._set_option("sort", mapping.copy())

    def skip(self, value: int) -> Self:  # ruff: ignore[undocumented-public-method]
        return self._set_option("skip", value)

    def limit(self, value: int) -> Self:  # ruff: ignore[undocumented-public-method]
        return self._set_option("limit", value)

    def batch_size(self, value: int) -> Self:  # ruff: ignore[undocumented-public-method]
        return self._set_option("batchSize", value)

    def projection(self, mapping: dict[str, Any]) -> Self:  # ruff: ignore[undocumented-public-method]
        return self._set_option("projection", mapping.copy())

    def comment(self, comment: str) -> Self:  # ruff: ignore[undocumented-public-method]
        return self._set_option("comment", comment)

    def hint(self, hint: str | dict[str, Any]) -> Self:  # ruff: ignore[undocumented-public-method]
        value = hint.copy() if isinstance(hint, dict) else hint
        return self._set_option("hint", value)

    def collation(self, collation: Collation) -> Self:  # ruff: ignore[undocumented-public-method]
        return self._set_option(
            "collation",
            maybe_to_dict(collation),
        )

    def read_preference(self, preference: ReadPreference) -> Self:
        """Override read routing before execution.

        Returns:
            This cursor.
        """
        self._ensure_at_start()
        self._read_preference = preference
        return self

    async def _command(self, command: dict[str, Any]) -> dict[str, Any]:
        response = await self._collection.database.client.command(
            command,
            db_name=self._server_database,
            session=self._session,
            server_address=self._server_address,
            read_preference=self._read_preference,
        )
        if self._server_address is None and isinstance(response, CommandReply):
            self._server_address = response.server_address

        return response

    def _get_query(self) -> dict[str, Any]:
        query = self._query.copy()
        options = self._options.copy()

        if "find" in query:
            query.update(options)
            query.setdefault("batchSize", 101)

            limit = query.get("limit", 0)
            if limit < 0:
                query["limit"] = abs(limit)
                query["singleBatch"] = True

            self._get_more_batch_size = query["batchSize"]
            return query

        uses_cursor_options = (
            "cursor" in query
            or any(
                name in query
                for name in (
                    "aggregate", "listIndexes", "listCollections", "bulkWrite",
                )
            )
        )

        if uses_cursor_options:
            cursor_options = query.get("cursor", {}).copy()

            if "batchSize" in options:
                cursor_options["batchSize"] = options.pop("batchSize")

            cursor_options.setdefault("batchSize", 101)
            query["cursor"] = cursor_options
            self._get_more_batch_size = cursor_options["batchSize"]

        elif "batchSize" in options:
            raise ValueError(
                "Cannot determine batchSize placement for this command; "
                "specify its initial batch options directly in the query",
            )

        query.update(options)
        return query

    def _map_docs(self, documents: list[dict[str, Any]]) -> list[T]:
        return [self._decoder(document) for document in documents]

    def _accept_batch(
        self,
        response: dict[str, Any],
        batch_key: str,
    ) -> None:
        cursor = response["cursor"]

        # Save the ID before mapping: mapping may fail, and cleanup
        # still needs to know which server cursor to kill.
        self._id = Int64(cursor["id"])

        namespace = cursor.get("ns")
        if namespace is not None:
            database, separator, collection = namespace.partition(".")
            if not database or not separator or not collection:
                raise ValueError(f"Invalid cursor namespace: {namespace!r}")
            self._server_database = database
            self._server_collection = collection

        self._docs.extend(self._map_docs(cursor[batch_key]))

    async def _start(self) -> None:
        self._started = True

        response = await self._command(self._get_query())

        if "cursor" in response:
            self._accept_batch(response, "firstBatch")
        else:
            # Preserve support for commands such as aggregate explain.
            self._command_response = response
            self._docs.append(cast("T", response))
            self._closed = True

    async def _get_more(self) -> None:
        if self._id is None or self._id == 0:
            raise RuntimeError("Cursor has no active server ID")

        command: dict[str, Any] = {
            "getMore": self._id,
            "collection": self._server_collection,
        }

        # batchSize=0 is useful for the initial request, but should
        # not be forwarded as a zero-sized getMore request.
        if self._get_more_batch_size > 0:
            command["batchSize"] = self._get_more_batch_size

        response = await self._command(command)
        self._accept_batch(response, "nextBatch")

    def _stop_iteration(self) -> NoReturn:
        self._closed = True
        raise StopAsyncIteration

    async def __anext__(self) -> T:
        self._ensure_single_thread()

        self._reading = True
        try:  # ruff: ignore[too-many-statements-in-try-clause]
            while True:
                # A final batch may contain documents even when id == 0.
                if self._docs:
                    return self._docs.popleft()

                if self._closed:
                    self._stop_iteration()

                if not self._started:
                    await self._start()

                elif self._id is None or self._id == 0:
                    self._closed = True
                    self._stop_iteration()
                else:
                    await self._get_more()

        except StopAsyncIteration:
            raise

        # Decoder failures and cancellation both require cursor cleanup.
        except BaseException as e:
            await self._close_after_error(e)
            raise

        finally:
            self._reading = False

    async def command_result(self) -> dict[str, Any]:
        """Execute a command and return its non-cursor response.

        Returns:
            The command response document.

        Raises:
            RuntimeError: If the cursor has already started or closed, or if
                the command returns a cursor instead of a direct response.
        """
        self._ensure_single_thread()

        if self._command_response is not None:
            return self._command_response

        self._ensure_at_start()

        self._reading = True
        try:
            await self._start()

            if self._command_response is None:
                raise RuntimeError("Command returned a cursor;")  # ruff: ignore[raise-within-try]

            self._docs.clear()
            return self._command_response  # ruff: ignore[try-consider-else]

        except BaseException as e:
            await self._close_after_error(e)
            raise

        finally:
            self._reading = False

    async def _close(self) -> None:
        cursor_id = self._id

        # Close locally before awaiting network I/O.
        self._closed = True
        self._id = None
        self._docs.clear()

        if cursor_id is None or cursor_id == 0:
            return

        await self._command({
            "killCursors": self._server_collection,
            "cursors": [cursor_id],
        })

    async def _close_after_error(
        self,
        error: BaseException,
    ) -> None:
        try:
            await self._close()
        except BaseException as e:
            # Preserve the original failure, including task cancellation.
            error.add_note(f"Cursor cleanup also failed: {e!r}")
            raise error from e

    async def close(self) -> None:
        """Close locally and attempt to kill the server cursor."""
        self._ensure_single_thread()

        await self._close()

    async def to_list(self) -> list[T]:
        """Retrieve all remaining documents from the cursor.

        Returns:
            A list containing all remaining documents.
        """
        return [document async for document in self]

    async def first(self) -> T:
        """Return the first document from the cursor's remaining results.

        Like ``to_list``, this method consumes results from the current cursor
        position. Repeated calls return the same value.

        Returns:
            The first document in the cursor's remaining results.
        """
        self._ensure_single_thread()
        if self._first_cached:
            return cast("T", self._first)

        document = await anext(self)
        self._first = document
        self._first_cached = True
        return document
