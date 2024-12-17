from __future__ import annotations

from typing import (
    List,
    Optional,
    TYPE_CHECKING,
    Any,
    Type,
    TypeVar,
    Union,
    Sequence,
    Literal
)

from bson import ObjectId
from typing_extensions import overload

from .typings import xJsonT
from .session import Transaction
from .cursor import Cursor
from .enums import ValidationLevel, IndexDirection, IndexType
from .models import Index, Collation, Update, ReadConcern, WriteConcern
from .schema import (
    Document,
    filter_non_null,
    ensure_document,
    maybe_to_dict
)

if TYPE_CHECKING:
    from .database import Database

T = TypeVar("T", bound=Document)
MaybeDocument = Union[xJsonT, Document]


class Collection:
    def __init__(
        self,
        name: str,
        database: Database,
        options: Optional[xJsonT] = None,
        info: Optional[xJsonT] = None
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
        coll = await self.database.list_collections({"name": self.name})
        if not coll:
            return await self.database.create_collection(self.name)
        return coll[0]

    async def with_options(self) -> Collection:
        infos = await self.database.list_collections({"name": self.name})
        if not infos:
            db = self.database.name
            raise Exception(
                f'namespace "{self.name}" not found in database "{db}"'
            )
        return infos[0]

    # https://www.mongodb.com/docs/manual/reference/command/collMod/
    async def coll_mod(self, params: xJsonT) -> None:
        await self.database.command({
            "collMod": self.name,
            **params
        })

    async def set_validator(
        self,
        validator: xJsonT,
        *,
        level: ValidationLevel = ValidationLevel.MODERATE
    ) -> None:
        await self.coll_mod({
            "validator": validator,
            "validationLevel": level.value.lower()
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
        comment: Optional[str] = None,
        transaction: Optional[Transaction] = None
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
        comment: Optional[str] = None,
        transaction: Optional[Transaction] = None
    ) -> List[ObjectId]:
        ...

    # https://www.mongodb.com/docs/manual/reference/command/insert/
    async def insert(
        self,
        ivalue: Union[MaybeDocument, Sequence[MaybeDocument]],
        /,
        *,
        ordered: bool = True,
        max_time_ms: int = 0,
        bypass_document_validation: bool = False,
        comment: Optional[str] = None,
        transaction: Optional[Transaction] = None
    ) -> Union[List[ObjectId], ObjectId]:
        multi = isinstance(ivalue, Sequence)
        if multi:
            docs = [ensure_document(doc, add_id=True) for doc in ivalue]
        else:
            docs = [ensure_document(ivalue, add_id=True)]
        command: xJsonT = filter_non_null({
            "insert": self.name,
            "ordered": ordered,
            "documents": docs,
            "maxTimeMS": max_time_ms,
            "bypassDocumentValidation": bypass_document_validation,
            "comment": comment
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
        comment: Optional[str] = None,
        let: Optional[xJsonT] = None,
        transaction: Optional[Transaction] = None
    ) -> int:
        command = filter_non_null({
            "update": self.name,
            "updates": [update.to_dict() for update in updates],
            "ordered": ordered,
            "maxTimeMS": max_time_ms,
            "bypassDocumentValidation": bypass_document_validation,
            "comment": comment,
            "let": let
        })

        request = await self.database.command(
            command,
            transaction=transaction
        )
        return request["nModified"]

    # .delete_one and .delete_many were separated because a limit.
    # Default is 0 but if you forget it youll lose all data
    # in collection. Naming saves situation
    async def delete_one(
        self,
        filter: Optional[xJsonT] = None,
        *,
        collation: Optional[Collation] = None,
        hint: Optional[Union[xJsonT, str]] = None,
        comment: Optional[str] = None,
        let: Optional[xJsonT] = None,
        ordered: bool = True,
        max_time_ms: int = 0,
        transaction: Optional[Transaction] = None
    ) -> bool:
        result = await self.delete_many(
            filter=filter,
            limit=1,
            collation=collation,
            hint=hint,
            comment=comment,
            let=let,
            ordered=ordered,
            max_time_ms=max_time_ms,
            transaction=transaction
        )
        return bool(result)

    # https://www.mongodb.com/docs/manual/reference/command/delete/
    async def delete_many(
        self,
        filter: Optional[xJsonT] = None,
        *,
        limit: int = 0,
        collation: Optional[Collation] = None,
        hint: Optional[Union[xJsonT, str]] = None,
        comment: Optional[str] = None,
        let: Optional[xJsonT] = None,
        ordered: bool = True,
        max_time_ms: int = 0,
        transaction: Optional[Transaction] = None
    ) -> int:
        params = filter_non_null({
            "delete": self.name,
            "ordered": ordered,
            "deletes": [filter_non_null({
                "q": filter or {},
                "limit": limit,
                "collation": maybe_to_dict(collation),
                "hint": hint
            })],
            "comment": comment,
            "let": let,
            "maxTimeMS": max_time_ms
        })
        request = await self.database.command(params, transaction=transaction)
        return request["n"]

    @overload
    async def find_one(
        self,
        filter: Optional[xJsonT],
        cls: Literal[None],
        transaction: Optional[Transaction] = None
    ) -> Optional[xJsonT]:
        ...

    @overload
    async def find_one(
        self,
        filter: Optional[xJsonT] = None,
        cls: Type[T] = Document,
        transaction: Optional[Transaction] = None
    ) -> Optional[T]:
        ...

    # same as .find but has implicit .to_list and limit 1
    async def find_one(
        self,
        filter: Optional[xJsonT] = None,
        cls: Optional[Type[T]] = None,
        transaction: Optional[Transaction] = None
    ) -> Union[Optional[T], Optional[xJsonT]]:
        documents = await self.find(
            filter=filter,
            cls=cls,
            transaction=transaction
        ).limit(1).to_list()
        if documents:
            return documents[0]

    @overload
    def find(
        self,
        filter: Optional[xJsonT],
        cls: Literal[None],
        transaction: Optional[Transaction] = None
    ) -> Cursor[xJsonT]:
        ...

    @overload
    def find(
        self,
        filter: Optional[xJsonT] = None,
        cls: Type[T] = Document,
        transaction: Optional[Transaction] = None
    ) -> Cursor[T]:
        ...

    def find(
        self,
        filter: Optional[xJsonT] = None,
        cls: Optional[Type[T]] = None,
        transaction: Optional[Transaction] = None
    ) -> Union[Cursor[T], Cursor[xJsonT]]:
        return Cursor(
            filter=filter or {},
            collection=self,
            cls=cls,
            transaction=transaction
        )

    # https://www.mongodb.com/docs/manual/reference/command/aggregate/
    async def aggregate(
        self,
        pipeline: List[xJsonT],
        *,
        explain: bool = False,
        allow_disk_use: bool = True,
        cursor: Optional[xJsonT] = None,
        max_time_ms: int = 0,
        bypass_document_validation: bool = False,
        read_concern: Optional[ReadConcern] = None,
        collation: Optional[Collation] = None,
        hint: Optional[str] = None,
        comment: Optional[str] = None,
        write_concern: Optional[WriteConcern] = None,
        let: Optional[xJsonT] = None,
        transaction: Optional[Transaction] = None
    ) -> List[Any]:
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
            "let": let
        })
        request = await self.database.command(
            command,
            transaction=transaction
        )
        return request["cursor"]["firstBatch"]

    # https://www.mongodb.com/docs/manual/reference/command/distinct/
    async def distinct(
        self,
        key: str,
        query: Optional[xJsonT] = None,
        collation: Optional[Collation] = None,
        comment: Optional[str] = None,
        read_concern: Optional[ReadConcern] = None,
        hint: Optional[str] = None,
        transaction: Optional[Transaction] = None
    ) -> List[Any]:
        command = filter_non_null({
            "distinct": self.name,
            "key": key,
            "query": query or {},
            "collation": maybe_to_dict(collation),
            "comment": comment,
            "readConcern": maybe_to_dict(read_concern),
            "hint": hint
        })
        request = await self.database.command(
            command,
            transaction=transaction
        )
        return request["values"]

    # https://www.mongodb.com/docs/manual/reference/command/count
    async def count(
        self,
        query: Optional[xJsonT] = None,
        limit: int = 0,
        skip: int = 0,
        hint: Optional[str] = None,
        collation: Optional[Collation] = None,
        comment: Optional[str] = None,
        max_time_ms: int = 0,
        read_concern: Optional[ReadConcern] = None,
        transaction: Optional[Transaction] = None
    ) -> int:
        command = filter_non_null({
            "count": self.name,
            "query": query or {},
            "limit": limit,
            "maxTimeMS": max_time_ms,
            "readConcern": maybe_to_dict(read_concern),
            "skip": skip,
            "hint": hint,
            "collation": maybe_to_dict(collation),
            "comment": comment
        })
        request = await self.database.command(command, transaction=transaction)
        return request["n"]

    # https://www.mongodb.com/docs/manual/reference/command/convertToCapped/
    async def convert_to_capped(
        self,
        size: int,
        write_concern: Optional[WriteConcern] = None,
        comment: Optional[str] = None
    ) -> None:
        if size <= 0:
            raise Exception("Cannot set size below zero.")
        command = filter_non_null({
            "convertToCapped": self.name,
            "size": size,
            "comment": comment,
            "writeConcern": maybe_to_dict(write_concern)
        })
        await self.database.command(command)

    # https://www.mongodb.com/docs/manual/reference/command/createIndexes/
    async def create_indexes(
        self,
        *indexes: Index,
        comment: Optional[str] = None
    ) -> None:
        if len(indexes) == 0:
            raise Exception("Empty sequence of indexes")
        command = filter_non_null({
            "createIndexes": self.name,
            "indexes": [
                index.to_dict() for index in indexes
            ],
            "comment": comment
        })
        await self.database.command(command)

    # https://www.mongodb.com/docs/manual/reference/command/listIndexes/
    async def list_indexes(self) -> List[Index]:
        r = await self.database.command({"listIndexes": self.name})
        info = r["cursor"]["firstBatch"]
        return [Index(
            name=idx["name"],
            key={
                k: IndexDirection(v) if isinstance(v, int) else IndexType(v)
                for k, v in idx["key"].items()
            },
            unique=idx.get("unique", False),
            hidden=idx.get("hidden", False)
        ) for idx in info]

    # https://www.mongodb.com/docs/manual/reference/command/reIndex/
    async def re_index(self) -> None:
        await self.database.command({"reIndex": self.name})

    # https://www.mongodb.com/docs/manual/reference/command/dropIndexes/
    async def drop_indexes(
        self,
        indexes: Optional[
            Union[str, List[str]]
        ] = None,
        drop_all: bool = False
    ) -> None:
        if drop_all and indexes is None:
            indexes = "*"
        await self.database.command({
            "dropIndexes": self.name,
            "index": indexes
        })
