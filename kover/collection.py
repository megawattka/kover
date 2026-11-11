"""Kover Collection Module."""

from __future__ import annotations

from typing import TYPE_CHECKING, Any, TypeVar, overload

from elune import ObjectId

from ._utils import classrepr, filter_non_null, maybe_to_dict, raw_decoder
from .cursor import Cursor
from .models.collection import ValidationLevel
from .models.indexes import Index, IndexDirection, IndexType
from .models.operations import Delete
from .schema.document import Document

if TYPE_CHECKING:
    from collections.abc import Sequence

    from .database import Database
    from .models.collation import Collation
    from .models.concerns import ReadConcern, WriteConcern
    from .models.operations import Update
    from .session import Session

T_co = TypeVar("T_co", bound=Document, covariant=True)


@classrepr("name", "database")
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
        options: dict[str, Any] | None = None,
        info: dict[str, Any] | None = None,
    ) -> None:
        self.name = name
        self.database = database
        self.options = options
        self.info = info

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
            database = self.database.name
            msg = f'namespace "{self.name}" not found in database "{database}"'
            raise ValueError(msg)
        return infos[0]

    # https://www.mongodb.com/docs/manual/reference/command/collMod/
    async def coll_mod(self, params: dict[str, Any]) -> None:
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
        validator: dict[str, Any],
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

    # https://www.mongodb.com/docs/manual/reference/command/insert/
    async def insert_one(
        self,
        document: dict[str, Any] | Document,
        /,
        *,
        ordered: bool = True,
        max_time_ms: int = 0,
        bypass_document_validation: bool = False,
        comment: str | None = None,
        session: Session | None = None,
    ) -> ObjectId:
        """Insert one document into the collection.

        Parameters:
            document : The document itself.
            ordered : Whether the inserts should be
                processed in order (default is True).
            max_time_ms : The maximum time in milliseconds
                for the operation (default is 0).
            bypass_document_validation : Allows the write to circumvent
                document validation (default is False).
            comment : A comment to attach to the operation.
            session : The logical session for the operation.

        Returns:
            The boolean value that indicates document insertion.
        """
        insertable = dict(maybe_to_dict(document))
        document_id = insertable.setdefault("_id", ObjectId())

        command: dict[str, Any] = filter_non_null({
            "insert": self.name,
            "ordered": ordered,
            "documents": [insertable],
            "maxTimeMS": max_time_ms,
            "bypassDocumentValidation": bypass_document_validation,
            "comment": comment,
        })
        await self.database.command(command, session=session)
        return document_id

    # https://www.mongodb.com/docs/manual/reference/command/insert/
    async def insert_many(
        self,
        documents: Sequence[dict[str, Any] | Document],
        /,
        *,
        ordered: bool = True,
        max_time_ms: int = 0,
        bypass_document_validation: bool = False,
        comment: str | None = None,
        session: Session | None = None,
    ) -> list[ObjectId]:
        """Insert many documents at once into the collection.

        Parameters:
            documents : sequence of documents.
            ordered : Whether the inserts should be
                processedin order (default is True).
            max_time_ms : The maximum time in milliseconds
                for the operation (default is 0).
            bypass_document_validation : Allows the write to circumvent
                document validation (default is False).
            comment : A comment to attach to the operation.
            session : The logical session for the operation.

        Returns:
            The amount of documents that were successfully inserted.
        """
        insertable = [dict(maybe_to_dict(document)) for document in documents]
        document_ids: list[ObjectId] = []
        for document in insertable:
            document_id = document.setdefault("_id", ObjectId())
            document_ids.append(document_id)

        command: dict[str, Any] = filter_non_null({
            "insert": self.name,
            "ordered": ordered,
            "documents": insertable,
            "maxTimeMS": max_time_ms,
            "bypassDocumentValidation": bypass_document_validation,
            "comment": comment,
        })
        await self.database.command(command, session=session)
        return document_ids

    # https://www.mongodb.com/docs/manual/reference/command/update/
    async def update(
        self,
        *updates: Update,
        ordered: bool = True,
        max_time_ms: int = 0,
        bypass_document_validation: bool = False,
        comment: str | None = None,
        let: dict[str, Any] | None = None,
        session: Session | None = None,
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
            session : The logical session for the operation.

        Returns:
            The number of documents updated.
        """
        command = filter_non_null({
            "update": self.name,
            "updates": [update.model_dump() for update in updates],
            "ordered": ordered,
            "maxTimeMS": max_time_ms,
            "bypassDocumentValidation": bypass_document_validation,
            "comment": comment,
            "let": let,
        })

        request = await self.database.command(
            command,
            session=session,
        )
        return request["nModified"]

    # https://www.mongodb.com/docs/manual/reference/command/delete
    async def delete(
        self,
        *deletes: Delete,
        comment: str | None = None,
        let: dict[str, Any] | None = None,
        ordered: bool = True,
        write_concern: WriteConcern | None = None,
        max_time_ms: int = 0,
        session: Session | None = None,
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
            session : The logical session for the operation.

        Returns:
            The number of documents deleted.
        """
        command = filter_non_null({
            "delete": self.name,
            "deletes": [delete.model_dump() for delete in deletes],
            "comment": comment,
            "let": let,
            "ordered": ordered,
            "writeConcern": maybe_to_dict(write_concern),
            "maxTimeMS": max_time_ms,
        })

        request = await self.database.command(
            command,
            session=session,
        )
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
        filter_: dict[str, Any] | None,
        cls: None = None,
        session: Session | None = None,
    ) -> dict[str, Any] | None:
        ...

    @overload
    async def find_one(
        self,
        filter_: dict[str, Any] | None = None,
        cls: type[T_co] = Document,
        session: Session | None = None,
    ) -> T_co | None:
        ...

    # same as .find but has explicit .to_list and limit 1
    async def find_one(
        self,
        filter_: dict[str, Any] | None = None,
        cls: type[T_co] | None = None,
        session: Session | None = None,
    ) -> T_co | dict[str, Any] | None:
        """Find a single document in the collection matching the filter.

        Parameters:
            filter_ : The filter criteria for selecting the document.
            cls : The class to deserialize the document into.
            session : The logical session for the operation.

        Returns:
            The first matching document or None if no document matches.
        """
        documents = await self.find(
            filter_=filter_,
            cls=cls,
            session=session,
        ).limit(1).to_list()
        if documents:
            return documents[0]
        return None

    @overload
    def find(
        self,
        filter_: dict[str, Any] | None = None,
        cls: None = None,
        session: Session | None = None,
    ) -> Cursor[dict[str, Any]]:
        ...

    @overload
    def find(
        self,
        filter_: dict[str, Any] | None,
        cls: type[T_co],
        session: Session | None = None,
    ) -> Cursor[T_co]:
        ...

    @overload
    def find(
        self,
        filter_: dict[str, Any] | None = None,
        *,
        cls: type[T_co],
        session: Session | None = None,
    ) -> Cursor[T_co]:
        ...

    def find(
        self,
        filter_: dict[str, Any] | None = None,
        cls: type[T_co] | None = None,
        session: Session | None = None,
    ) -> Cursor[T_co] | Cursor[dict[str, Any]]:
        """Find documents in the collection matching the filter.

        Parameters:
            filter_ : The filter criteria for selecting documents.
            cls : The class to deserialize the documents into.
            session : The logical session for the operation.

        Returns:
            A cursor for iterating over the matching documents.
        """
        query = {
            "find": self.name,
            "filter": filter_ or {},
        }

        if cls is None:
            return Cursor(
                query=query,
                collection=self,
                decoder=raw_decoder,
                session=session,
            )

        return Cursor(
            query=query,
            collection=self,
            decoder=cls.model_validate,
            session=session,
        )

    # TODO @megawattka: prob make overloads for cls like in "find"?
    # https://www.mongodb.com/docs/manual/reference/command/aggregate/
    def aggregate(
        self,
        pipeline: list[dict[str, Any]],
        *,
        explain: bool = False,
        allow_disk_use: bool = True,
        cursor: dict[str, Any] | None = None,
        max_time_ms: int = 0,
        bypass_document_validation: bool = False,
        read_concern: ReadConcern | None = None,
        collation: Collation | None = None,
        hint: str | None = None,
        comment: str | None = None,
        write_concern: WriteConcern | None = None,
        let: dict[str, Any] | None = None,
        session: Session | None = None,
    ) -> Cursor[dict[str, Any]]:
        """Create a cursor for an aggregation pipeline on the collection.

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
            session : The logical session.

        Returns:
            A cursor for iterating over the aggregation results.
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
        return Cursor(
            query=command,
            collection=self,
            decoder=raw_decoder,
            session=session,
        )

    # https://www.mongodb.com/docs/manual/reference/command/distinct/
    async def distinct(
        self,
        key: str,
        query: dict[str, Any] | None = None,
        collation: Collation | None = None,
        comment: str | None = None,
        read_concern: ReadConcern | None = None,
        hint: str | None = None,
        session: Session | None = None,
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
            session : The logical session for the operation.

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
            session=session,
        )
        return request["values"]

    # https://www.mongodb.com/docs/manual/reference/command/count
    async def count(
        self,
        query: dict[str, Any] | None = None,
        limit: int = 0,
        skip: int = 0,
        hint: str | None = None,
        collation: Collation | None = None,
        comment: str | None = None,
        max_time_ms: int = 0,
        read_concern: ReadConcern | None = None,
        session: Session | None = None,
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
            session : The logical session for the operation.

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
        request = await self.database.command(command, session=session)
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
                index.model_dump() for index in indexes
            ],
            "comment": comment,
        })
        await self.database.command(command)

    # https://www.mongodb.com/docs/manual/reference/command/listIndexes/
    async def list_indexes(self) -> list[Index]:
        """List all indexes on the collection.

        Returns:
            Index objects representing the collection's indexes.
        """
        cursor: Cursor[dict[str, Any]] = Cursor({
            "listIndexes": self.name,
        }, collection=self, decoder=raw_decoder)

        return [
            Index(
                name=document["name"],
                key={
                    key: (
                        IndexDirection(value)
                        if isinstance(value, int)
                        else IndexType(value)
                    )
                    for key, value in document["key"].items()
                },
                unique=document.get("unique", False),
                hidden=document.get("hidden", False),
            )
            async for document in cursor
        ]

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
        *,
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
