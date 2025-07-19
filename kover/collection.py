from __future__ import annotations

from collections.abc import Sequence
from typing import TYPE_CHECKING, Any, TypeVar

from typing_extensions import overload

from .bson import ObjectId
from .cursor import Cursor
from .enums import IndexDirection, IndexType, ValidationLevel
from .models import (
    Delete,
    Index,
)
from .schema import Document
from .utils import filter_non_null, maybe_to_dict

if TYPE_CHECKING:
    from .database import Database
    from .models import (
        Collation,
        ReadConcern,
        Update,
        WriteConcern,
    )
    from .session import Transaction
    from .typings import xJsonT

T = TypeVar("T", bound=Document)


class Collection:
    """Collection.

    Represents a MongoDB collection and provides methods for CRUD operations,
    index management, aggregation, and other collection-level commands.

    Attributes:
        name : The name of the collection.
        database : The database instance to which the collection belongs.
        options : Optional collection options.
        info : Optional collection metadata.
    """

    def __init__(
        self,
        name: str,
        database: Database,
        options: xJsonT | None = None,
        info: xJsonT | None = None,
    ) -> None:
        self.name = name
        self.database = database
        self.options = options
        self.info = info

    def __repr__(self) -> str:
        return f"Collection(name={self.name})"

    def __getattr__(self, name: str) -> Collection:
        return self.database.get_collection(f"{self.name}.{name}")

    async def create_if_not_exists(self) -> Collection:
        """Return the created collection or return the existing collection.

        Returns:
            The created or existing collection.
        """
        coll = await self.database.list_collections({"name": self.name})
        if not coll:
            return await self.database.create_collection(self.name)
        return coll[0]

    async def with_options(self) -> Collection:
        """Retrieve the collection with its options from the database.

        Returns:
            The collection object with its options.

        Raises:
            ValueError : If the collection
                namespace is not found in the database.
        """
        infos = await self.database.list_collections({"name": self.name})
        if not infos:
            db = self.database.name
            msg = f'namespace "{self.name}" not found in database "{db}"'
            raise ValueError(msg)
        return infos[0]

    # https://www.mongodb.com/docs/manual/reference/command/collMod/
    async def coll_mod(self, params: xJsonT) -> None:
        """Modify collection settings using the collMod command.

        Parameters:
            params : Dictionary of parameters to pass to the collMod command.
        """
        await self.database.command({
            "collMod": self.name,
            **params,
        })

    async def set_validator(
        self,
        validator: xJsonT,
        *,
        level: ValidationLevel = ValidationLevel.MODERATE,
    ) -> None:
        """Set a validator for the collection.

        Parameters:
            validator : The validation rules to apply
                to documents in the collection.
            level : The validation level to use (default is MODERATE).
        """
        await self.coll_mod({
            "validator": validator,
            "validationLevel": level.value.lower(),
        })

    @overload
    async def insert(
        self,
        ivalue: xJsonT | Document,
        /,
        *,
        ordered: bool = True,
        max_time_ms: int = 0,
        bypass_document_validation: bool = False,
        comment: str | None = None,
        transaction: Transaction | None = None,
    ) -> ObjectId:
        ...

    @overload
    async def insert(
        self,
        ivalue: Sequence[xJsonT | Document],
        /,
        *,
        ordered: bool = True,
        max_time_ms: int = 0,
        bypass_document_validation: bool = False,
        comment: str | None = None,
        transaction: Transaction | None = None,
    ) -> list[ObjectId]:
        ...

    # https://www.mongodb.com/docs/manual/reference/command/insert/
    async def insert(
        self,
        ivalue: xJsonT | Document | Sequence[xJsonT | Document],
        /,
        *,
        ordered: bool = True,
        max_time_ms: int = 0,
        bypass_document_validation: bool = False,
        comment: str | None = None,
        transaction: Transaction | None = None,
    ) -> list[ObjectId] | ObjectId:
        """Insert one or more documents into the collection.

        Parameters:
            ivalue : The document or sequence of documents to insert.
            ordered : Whether the inserts should be
                processedin order (default is True).
            max_time_ms : The maximum time in milliseconds
                for the operation (default is 0).
            bypass_document_validation : Allows the write to circumvent
                document validation (default is False).
            comment : A comment to attach to the operation.
            transaction : The transaction context for the operation.

        Returns:
            The ObjectId(s) of the inserted document(s).
        """
        multi = isinstance(ivalue, Sequence)
        if multi:
            docs = [
                doc.to_dict() if isinstance(doc, Document) else doc for doc in ivalue   # noqa: E501
            ]
        else:
            docs = [ivalue.to_dict() if isinstance(ivalue, Document) else ivalue]  # noqa: E501
        for doc in docs:
            doc.setdefault("_id", ObjectId())
        command: xJsonT = filter_non_null({
            "insert": self.name,
            "ordered": ordered,
            "documents": docs,
            "maxTimeMS": max_time_ms,
            "bypassDocumentValidation": bypass_document_validation,
            "comment": comment,
        })
        await self.database.command(command, transaction=transaction)
        inserted = [
            doc["_id"] for doc in docs
        ]
        return inserted[0] if not multi else inserted

    # https://www.mongodb.com/docs/manual/reference/command/update/
    async def update(
        self,
        *updates: Update,
        ordered: bool = True,
        max_time_ms: int = 0,
        bypass_document_validation: bool = False,
        comment: str | None = None,
        let: xJsonT | None = None,
        transaction: Transaction | None = None,
    ) -> int:
        """Update documents in the collection.

        Parameters:
            updates : One or more Update objects specifying
                the update criteria and modifications.
            ordered : Whether the updates should
                be processed in order (default is True).
            max_time_ms : The maximum time in milliseconds
                for the operation (default is 0).
            bypass_document_validation : Allows the write
                to circumvent document validation (default is False).
            comment : A comment to attach to the operation.
            let : Variables that can be used in the update expressions.
            transaction : The transaction context for the operation.

        Returns:
            The number of documents updated.
        """
        command = filter_non_null({
            "update": self.name,
            "updates": [update.to_dict() for update in updates],
            "ordered": ordered,
            "maxTimeMS": max_time_ms,
            "bypassDocumentValidation": bypass_document_validation,
            "comment": comment,
            "let": let,
        })

        request = await self.database.command(
            command,
            transaction=transaction,
        )
        return request["nModified"]

    # https://www.mongodb.com/docs/manual/reference/command/delete
    async def delete(
        self,
        *deletes: Delete,
        comment: str | None = None,
        let: xJsonT | None = None,
        ordered: bool = True,
        write_concern: WriteConcern | None = None,
        max_time_ms: int = 0,
        transaction: Transaction | None = None,
    ) -> int:
        """Delete documents from the collection.

        Parameters:
            deletes : One or more Delete objects
                specifying the deletion criteria.
            comment : A comment to attach to the operation.
            let : Variables that can be used in the delete expressions.
            ordered : Whether the deletes should be processed in order.
            write_concern : The write concern for the operation.
            max_time_ms : The maximum amount of time
                to allow the operation to run.
            transaction : The transaction context for the operation.

        Returns:
            The number of documents deleted.
        """
        command = filter_non_null({
            "delete": self.name,
            "deletes": [delete.to_dict() for delete in deletes],
            "comment": comment,
            "let": let,
            "ordered": ordered,
            "writeConcern": maybe_to_dict(write_concern),
            "maxTimeMS": max_time_ms,
        })
        request = await self.database.command(command, transaction=transaction)
        return request["n"]

    # custom function not stated in docs
    # used to delete all docs from collection
    async def clear(self) -> int:
        """Delete all documents from the collection.

        Returns:
            The number of documents deleted.
        """
        deletion = Delete({}, limit=0)
        return await self.delete(deletion)

    @overload
    async def find_one(
        self,
        filter_: xJsonT | None,
        cls: None = None,
        transaction: Transaction | None = None,
    ) -> xJsonT | None:
        ...

    @overload
    async def find_one(
        self,
        filter_: xJsonT | None = None,
        cls: type[T] = Document,
        transaction: Transaction | None = None,
    ) -> T | None:
        ...

    # same as .find but has implicit .to_list and limit 1
    async def find_one(
        self,
        filter_: xJsonT | None = None,
        cls: type[T] | None = None,
        transaction: Transaction | None = None,
    ) -> T | xJsonT | None:
        """Find a single document in the collection matching the filter.

        Parameters:
            filter_ : The filter criteria for selecting the document.
            cls : The class to deserialize the document into.
            transaction : The transaction context for the operation.

        Returns:
            The first matching document or None if no document matches.
        """
        documents = await self.find(
            filter_=filter_,
            cls=cls,
            transaction=transaction,
        ).limit(1).to_list()
        if documents:
            return documents[0]
        return None

    @overload
    def find(
        self,
        filter_: xJsonT | None,
        cls: None,
        transaction: Transaction | None = None,
    ) -> Cursor[xJsonT]:
        ...

    @overload
    def find(
        self,
        filter_: xJsonT | None = None,
        cls: type[T] = Document,
        transaction: Transaction | None = None,
    ) -> Cursor[T]:
        ...

    def find(
        self,
        filter_: xJsonT | None = None,
        cls: type[T] | None = None,
        transaction: Transaction | None = None,
    ) -> Cursor[T] | Cursor[xJsonT]:
        """Find documents in the collection matching the filter.

        Parameters:
            filter_ : The filter criteria for selecting documents.
            cls : The class to deserialize the documents into.
            transaction : The transaction context for the operation.

        Returns:
            A cursor for iterating over the matching documents.
        """
        return Cursor(
            filter_=filter_ or {},
            collection=self,
            cls=cls,
            transaction=transaction,
        )

    # TODO @megawattka: prob make overloads for cls like in "find"?
    # https://www.mongodb.com/docs/manual/reference/command/aggregate/
    async def aggregate(
        self,
        pipeline: list[xJsonT],
        *,
        explain: bool = False,
        allow_disk_use: bool = True,
        cursor: xJsonT | None = None,
        max_time_ms: int = 0,
        bypass_document_validation: bool = False,
        read_concern: ReadConcern | None = None,
        collation: Collation | None = None,
        hint: str | None = None,
        comment: str | None = None,
        write_concern: WriteConcern | None = None,
        let: xJsonT | None = None,
        transaction: Transaction | None = None,
    ) -> list[Any]:
        """Run an aggregation pipeline on the collection.

        Parameters:
            pipeline : The aggregation pipeline stages.
            explain : Whether to return information on
                the execution of the pipeline.
            allow_disk_use : Enables writing to temporary files.
            cursor : The cursor options.
            max_time_ms : The maximum time in milliseconds for the operation.
            bypass_document_validation : Allows the write
                to circumvent document validation.
            read_concern : The read concern for the operation.
            collation : The collation to use for string comparison.
            hint : Index to use.
            comment : Comment to attach to the operation.
            write_concern : The write concern for the operation.
            let : Variables for use in the pipeline.
            transaction : The transaction context.

        Returns:
            The result documents from the aggregation.
        """
        command = filter_non_null({
            "aggregate": self.name,
            "pipeline": pipeline,
            "cursor": cursor or {},
            "explain": explain,
            "allowDiskUse": allow_disk_use,
            "maxTimeMS": max_time_ms,
            "bypassDocumentValidation": bypass_document_validation,
            "readConcern": maybe_to_dict(read_concern),
            "collation": maybe_to_dict(collation),
            "hint": hint,
            "comment": comment,
            "writeConcern": maybe_to_dict(write_concern),
            "let": let,
        })
        request = await self.database.command(
            command,
            transaction=transaction,
        )
        cursor_id = int(request["cursor"]["id"])
        docs: list[xJsonT] = request["cursor"]["firstBatch"]
        if cursor_id != 0:
            next_req = await self.database.command({
                "getMore": cursor_id,
                "collection": self.name,
            })
            docs.extend(next_req["cursor"]["nextBatch"])
        return docs

    # https://www.mongodb.com/docs/manual/reference/command/distinct/
    async def distinct(
        self,
        key: str,
        query: xJsonT | None = None,
        collation: Collation | None = None,
        comment: str | None = None,
        read_concern: ReadConcern | None = None,
        hint: str | None = None,
        transaction: Transaction | None = None,
    ) -> list[object]:
        """Return a list of distinct values for the specified key.

        Parameters:
            key : The field for which to return distinct values.
            query : A query that specifies the documents from
                which to retrieve distinct values.
            collation : Specifies a collation for string comparison.
            comment : A comment to attach to the operation.
            read_concern : The read concern for the operation.
            hint : Index to use.
            transaction : The transaction context for the operation.

        Returns:
            The list of distinct values for the specified key.
        """
        command = filter_non_null({
            "distinct": self.name,
            "key": key,
            "query": query or {},
            "collation": maybe_to_dict(collation),
            "comment": comment,
            "readConcern": maybe_to_dict(read_concern),
            "hint": hint,
        })
        request = await self.database.command(
            command,
            transaction=transaction,
        )
        return request["values"]

    # https://www.mongodb.com/docs/manual/reference/command/count
    async def count(
        self,
        query: xJsonT | None = None,
        limit: int = 0,
        skip: int = 0,
        hint: str | None = None,
        collation: Collation | None = None,
        comment: str | None = None,
        max_time_ms: int = 0,
        read_concern: ReadConcern | None = None,
        transaction: Transaction | None = None,
    ) -> int:
        """Count the number of documents in the collection matching the query.

        Parameters:
            query : The filter criteria for selecting documents.
            limit : The maximum number of documents to count.
            skip : The number of documents to skip before counting.
            hint : Index to use.
            collation : Specifies a collation for string comparison.
            comment : A comment to attach to the operation.
            max_time_ms : The maximum time in milliseconds for the operation.
            read_concern : The read concern for the operation.
            transaction : The transaction context for the operation.

        Returns:
            The number of documents matching the query.
        """
        command = filter_non_null({
            "count": self.name,
            "query": query or {},
            "limit": limit,
            "maxTimeMS": max_time_ms,
            "readConcern": maybe_to_dict(read_concern),
            "skip": skip,
            "hint": hint,
            "collation": maybe_to_dict(collation),
            "comment": comment,
        })
        request = await self.database.command(command, transaction=transaction)
        return request["n"]

    # https://www.mongodb.com/docs/manual/reference/command/convertToCapped/
    async def convert_to_capped(
        self,
        size: int,
        write_concern: WriteConcern | None = None,
        comment: str | None = None,
    ) -> None:
        """Convert the collection to a capped with the specified size.

        Parameters:
            size : The maximum size in bytes for the capped collection.
            write_concern : The write concern for the operation.
            comment : A comment to attach to the operation.

        Raises:
            ValueError : If the specified size is less than or equal to zero.
        """
        if size <= 0:
            raise ValueError("Cannot set size below zero.")
        command = filter_non_null({
            "convertToCapped": self.name,
            "size": size,
            "comment": comment,
            "writeConcern": maybe_to_dict(write_concern),
        })
        await self.database.command(command)

    # https://www.mongodb.com/docs/manual/reference/command/createIndexes/
    async def create_indexes(
        self,
        *indexes: Index,
        comment: str | None = None,
    ) -> None:
        """Create one or more indexes on the collection.

        Parameters:
            indexes : One or more Index objects
                specifying the indexes to create.
            comment : A comment to attach to the operation.

        Raises:
            ValueError : If no indexes are provided.
        """
        if len(indexes) == 0:
            raise ValueError("Empty sequence of indexes")
        command = filter_non_null({
            "createIndexes": self.name,
            "indexes": [
                index.to_dict() for index in indexes
            ],
            "comment": comment,
        })
        await self.database.command(command)

    # https://www.mongodb.com/docs/manual/reference/command/listIndexes/
    async def list_indexes(self) -> list[Index]:
        """List all indexes on the collection.

        Returns:
            A list of Index objects representing the indexes on the collection.
        """
        r = await self.database.command({"listIndexes": self.name})
        info = r["cursor"]["firstBatch"]
        return [Index(
            name=idx["name"],
            key={
                k: IndexDirection(v) if isinstance(v, int) else IndexType(v)
                for k, v in idx["key"].items()
            },
            unique=idx.get("unique", False),
            hidden=idx.get("hidden", False),
        ) for idx in info]

    # https://www.mongodb.com/docs/manual/reference/command/reIndex/
    async def re_index(self) -> None:
        """Rebuild all indexes on the collection.

        This operation drops and recreates all indexes on the collection.
        """
        await self.database.command({"reIndex": self.name})

    # https://www.mongodb.com/docs/manual/reference/command/dropIndexes/
    async def drop_indexes(
        self,
        indexes: str | list[str] | None = None,
        drop_all: bool = False,
    ) -> None:
        """Drop one or more indexes from the collection.

        Parameters:
            indexes : The name(s) of the index(es) to drop.
                If None and drop_all is True, all indexes are dropped.
            drop_all : If True and indexes is None,
                all indexes will be dropped.
        """
        if drop_all and indexes is None:
            indexes = "*"
        await self.database.command({
            "dropIndexes": self.name,
            "index": indexes,
        })

    async def drop(self) -> None:
        """Drop current collection.

        This operation drops collection entirely,
        without any data recovery options.
        """
        await self.database.drop_collection(self.name)
