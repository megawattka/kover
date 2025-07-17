from __future__ import annotations

from collections.abc import Sequence
from typing import TYPE_CHECKING, TypeVar

from typing_extensions import overload

from .bson import ObjectId
from .cursor import Cursor
from .enums import IndexDirection, IndexType, ValidationLevel
from .models import (
    Delete,
    Index,
)
from .schema import Document
from .typings import xJsonT
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

T = TypeVar("T", bound=Document)
MaybeDocument = xJsonT | Document


class Collection:
    """Collection.

    Represents a MongoDB collection and provides methods for CRUD operations,
    index management, aggregation, and other collection-level commands.

    Attributes:
    ----------
    name : str
        The name of the collection.
    database : Database
        The database instance to which the collection belongs.
    options : xJsonT | None
        Optional collection options.
    info : xJsonT | None
        Optional collection metadata.

    Methods:
    -------
    create_if_not_exists()
        Create the collection if it does not exist.
    with_options()
        Retrieve the collection with its options.
    coll_mod(params)
        Modify collection settings.
    set_validator(validator, level)
        Set a validator for the collection.
    insert(ivalue, ...)
        Insert documents into the collection.
    update(*updates, ...)
        Update documents in the collection.
    delete(*deletes, ...)
        Delete documents from the collection.
    clear()
        Delete all documents from the collection.
    find_one(filter_, cls, ...)
        Find a single document.
    find(filter_, cls, ...)
        Find documents.
    aggregate(pipeline, ...)
        Run an aggregation pipeline.
    distinct(key, ...)
        Get distinct values for a key.
    count(query, ...)
        Count documents matching a query.
    convert_to_capped(size, ...)
        Convert the collection to capped.
    create_indexes(*indexes, ...)
        Create indexes.
    list_indexes()
        List all indexes.
    re_index()
        Rebuild all indexes.
    drop_indexes(indexes, drop_all)
        Drop indexes.
    drop()
        Drop the collection.
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
        """Create the collection if it does not exist, otherwise return the existing collection.

        Returns:
        -------
        Collection
            The created or existing collection.
        """  # noqa: E501
        coll = await self.database.list_collections({"name": self.name})
        if not coll:
            return await self.database.create_collection(self.name)
        return coll[0]

    async def with_options(self) -> Collection:
        """Retrieve the collection with its options from the database.

        Returns:
        -------
        Collection
            The collection object with its options.

        Raises:
        ------
        NameSpaceNotFoundError
            If the collection namespace is not found in the database.
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
        ----------
        params : xJsonT
            Dictionary of parameters to pass to the collMod command.

        Returns:
        -------
        None
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
        ----------
        validator : xJsonT
            The validation rules to apply to documents in the collection.
        level : ValidationLevel, optional
            The validation level to use (default is MODERATE).

        Returns:
        -------
        None
        """
        await self.coll_mod({
            "validator": validator,
            "validationLevel": level.value.lower(),
        })

    @overload
    async def insert(
        self,
        ivalue: MaybeDocument,
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
        ivalue: Sequence[MaybeDocument],
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
        ivalue: MaybeDocument | Sequence[MaybeDocument],
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
        ----------
        ivalue : MaybeDocument or Sequence[MaybeDocument]
            The document or sequence of documents to insert.
        ordered : bool, optional
            Whether the inserts should be processed in order (default is True).
        max_time_ms : int, optional
            The maximum time in milliseconds for the operation (default is 0).
        bypass_document_validation : bool, optional
            Allows the write to circumvent document validation (default is False).
        comment : str or None, optional
            A comment to attach to the operation.
        transaction : Transaction or None, optional
            The transaction context for the operation.

        Returns:
        -------
        ObjectId or list[ObjectId]
            The ObjectId(s) of the inserted document(s).
        """  # noqa: E501
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
        """Update documents in the collection according to the specified update operations.

        Parameters:
        ----------
        updates : Update
            One or more Update objects specifying the update criteria and modifications.
        ordered : bool, optional
            Whether the updates should be processed in order (default is True).
        max_time_ms : int, optional
            The maximum time in milliseconds for the operation (default is 0).
        bypass_document_validation : bool, optional
            Allows the write to circumvent document validation (default is False).
        comment : str or None, optional
            A comment to attach to the operation.
        let : xJsonT or None, optional
            Variables that can be used in the update expressions.
        transaction : Transaction or None, optional
            The transaction context for the operation.

        Returns:
        -------
        int
            The number of documents updated.
        """  # noqa: E501
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
        """Delete documents from the collection according to the specified delete operations.

        Parameters:
        ----------
        deletes : Delete
            One or more Delete objects specifying the deletion criteria.
        comment : str, optional
            A comment to attach to the operation.
        let : xJsonT, optional
            Variables that can be used in the delete expressions.
        ordered : bool, optional
            Whether the deletes should be processed in order.
        write_concern : WriteConcern, optional
            The write concern for the operation.
        max_time_ms : int, optional
            The maximum amount of time to allow the operation to run.
        transaction : Transaction, optional
            The transaction context for the operation.

        Returns:
        -------
        int
            The number of documents deleted.
        """  # noqa: E501
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
        -------
        int
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
        ----------
        filter_ : xJsonT or None, optional
            The filter criteria for selecting the document.
        cls : type[T] or None, optional
            The class to deserialize the document into.
        transaction : Transaction or None, optional
            The transaction context for the operation.

        Returns:
        -------
        T or xJsonT or None
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
        ----------
        filter_ : xJsonT or None, optional
            The filter criteria for selecting documents.
        cls : type[T] or None, optional
            The class to deserialize the documents into.
        transaction : Transaction or None, optional
            The transaction context for the operation.

        Returns:
        -------
        Cursor[T] or Cursor[xJsonT]
            A cursor for iterating over the matching documents.
        """
        return Cursor(
            filter_=filter_ or {},
            collection=self,
            cls=cls,
            transaction=transaction,
        )

    # TODO @megawattka: prob make overloads for cls like in "find"
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
    ) -> list[xJsonT]:
        """Run an aggregation pipeline on the collection.

        Parameters:
        ----------
        pipeline : list[xJsonT]
            The aggregation pipeline stages.
        explain : bool, optional
            Whether to return information on the execution of the pipeline.
        allow_disk_use : bool, optional
            Enables writing to temporary files.
        cursor : xJsonT or None, optional
            The cursor options.
        max_time_ms : int, optional
            The maximum time in milliseconds for the operation.
        bypass_document_validation : bool, optional
            Allows the write to circumvent document validation.
        read_concern : ReadConcern or None, optional
            The read concern for the operation.
        collation : Collation or None, optional
            The collation to use for string comparison.
        hint : str or None, optional
            Index to use.
        comment : str or None, optional
            Comment to attach to the operation.
        write_concern : WriteConcern or None, optional
            The write concern for the operation.
        let : xJsonT or None, optional
            Variables for use in the pipeline.
        transaction : Transaction or None, optional
            The transaction context.

        Returns:
        -------
        list[xJsonT]
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
        """Return a list of distinct values for the specified key in the collection.

        Parameters:
        ----------
        key : str
            The field for which to return distinct values.
        query : xJsonT or None, optional
            A query that specifies the documents from which to retrieve distinct values.
        collation : Collation or None, optional
            Specifies a collation for string comparison.
        comment : str or None, optional
            A comment to attach to the operation.
        read_concern : ReadConcern or None, optional
            The read concern for the operation.
        hint : str or None, optional
            Index to use.
        transaction : Transaction or None, optional
            The transaction context for the operation.

        Returns:
        -------
        list[object]
            The list of distinct values for the specified key.
        """  # noqa: E501
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
        ----------
        query : xJsonT or None, optional
            The filter criteria for selecting documents.
        limit : int, optional
            The maximum number of documents to count.
        skip : int, optional
            The number of documents to skip before counting.
        hint : str or None, optional
            Index to use.
        collation : Collation or None, optional
            Specifies a collation for string comparison.
        comment : str or None, optional
            A comment to attach to the operation.
        max_time_ms : int, optional
            The maximum time in milliseconds for the operation.
        read_concern : ReadConcern or None, optional
            The read concern for the operation.
        transaction : Transaction or None, optional
            The transaction context for the operation.

        Returns:
        -------
        int
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
        """Convert the collection to a capped collection with the specified size.

        Parameters:
        ----------
        size : int
            The maximum size in bytes for the capped collection.
        write_concern : WriteConcern or None, optional
            The write concern for the operation.
        comment : str or None, optional
            A comment to attach to the operation.

        Raises:
        ------
        ValueError
            If the specified size is less than or equal to zero.
        """  # noqa: E501
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
        ----------
        indexes : Index
            One or more Index objects specifying the indexes to create.
        comment : str or None, optional
            A comment to attach to the operation.

        Raises:
        ------
        ValueError
            If no indexes are provided.
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
        -------
        list[Index]
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
        ----------
        indexes : str or list[str] or None, optional
            The name(s) of the index(es) to drop. If None and drop_all is True, all indexes are dropped.
        drop_all : bool, optional
            If True and indexes is None, all indexes will be dropped.

        Returns:
        -------
        None
        """  # noqa: E501
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
