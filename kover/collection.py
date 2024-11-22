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
)

from bson import ObjectId
from typing_extensions import overload

from .typings import xJsonT
from .session import Transaction
from .cursor import Cursor
from .schema import Document, filter_non_null
from .enums import ValidationLevel
from .models import Index

if TYPE_CHECKING:
    from .database import Database

T = TypeVar("T", bound=Document)


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

    async def coll_mod(self, params: xJsonT) -> None:
        await self.database.command({
            "collMod": self.name,
            **params
        })

    async def set_validator(
        self,
        validator: xJsonT,
        level: ValidationLevel = ValidationLevel.MODERATE
    ) -> None:
        await self.coll_mod({
            "validator": validator,
            "validationLevel": level.value.lower()
        })

    async def insert_one(
        self,
        doc: Union[xJsonT, Document],
        transaction: Optional[Transaction] = None
    ) -> ObjectId:
        if isinstance(doc, Document):
            doc = doc.to_dict()
        doc = doc.copy()
        doc.setdefault("_id", ObjectId())
        command: xJsonT = {
            "insert": self.name,
            "ordered": True,
            "documents": [doc]
        }
        await self.database.command(command, transaction=transaction)
        return doc["_id"]

    async def insert_many(
        self,
        docs: Sequence[Union[xJsonT, Document]],
        transaction: Optional[Transaction] = None
    ) -> List[ObjectId]:
        assert len(docs) > 0, "Empty sequence of documents"
        needed: List[xJsonT] = []
        for doc in docs:
            if isinstance(doc, Document):
                doc = doc.to_dict()
            doc.setdefault("_id", ObjectId())
            needed.append(doc)
        command: xJsonT = {
            "insert": self.name,
            "ordered": True,
            "documents": needed
        }
        await self.database.command(command, transaction=transaction)
        return [
            doc["_id"] for doc in needed
        ]

    async def update_one(
        self,
        filter: xJsonT,
        to_replace: xJsonT,
        upsert: bool = False,
        transaction: Optional[Transaction] = None
    ) -> int:
        command: xJsonT = {
            "update": self.name,
            "ordered": True,
            "updates": [{
                "q": filter,
                "u": {
                    "$set": to_replace
                },
                "multi": False,
                "upsert": upsert
            }]
        }
        request = await self.database.command(command, transaction=transaction)
        return request["nModified"]

    async def update_many(
        self,
        filter: xJsonT,
        to_replace: xJsonT,
        upsert: bool = False,
        transaction: Optional[Transaction] = None
    ) -> int:
        params: xJsonT = {
            "update": self.name,
            "ordered": True,
            "updates": [{
                "q": filter,
                "u": {
                    "$set": to_replace
                },
                "multi": True,
                "upsert": upsert
            }]
        }
        request = await self.database.command(params, transaction=transaction)
        return request["nModified"]

    async def delete_one(
        self,
        filter: Optional[xJsonT] = None,
        transaction: Optional[Transaction] = None
    ) -> bool:
        params: xJsonT = {
            "delete": self.name,
            "ordered": True,
            "deletes": [{
                "q": filter or {},
                "limit": 1
            }]
        }
        request = await self.database.command(params, transaction=transaction)
        return bool(request["n"])

    async def delete_many(
        self,
        filter: Optional[xJsonT] = None,
        limit: int = 0,
        transaction: Optional[Transaction] = None
    ) -> int:
        params: xJsonT = {
            "delete": self.name,
            "ordered": True,
            "deletes": [{
                "q": filter or {},
                "limit": limit
            }]
        }
        request = await self.database.command(params, transaction=transaction)
        return request["n"]

    @overload
    async def find_one(
        self,
        filter: Optional[xJsonT] = None,
        cls: None = None,
        transaction: Optional[Transaction] = None
    ) -> Optional[xJsonT]:
        ...

    @overload
    async def find_one(
        self,
        filter: Optional[xJsonT],
        cls: Type[T],
        transaction: Optional[Transaction]
    ) -> Optional[T]:
        ...

    @overload
    async def find_one(
        self,
        filter: Optional[xJsonT] = None,
        cls: Type[T] = ...,
        transaction: Optional[Transaction] = ...
    ) -> Optional[T]:
        ...

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
        return None

    @overload
    def find(
        self,
        filter: Optional[xJsonT],
        cls: Type[T],
        transaction: Optional[Transaction]
    ) -> Cursor[T]:
        ...

    @overload
    def find(
        self,
        filter: Optional[xJsonT] = None,
        cls: None = None,
        transaction: Optional[Transaction] = None
    ) -> Cursor[xJsonT]:
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

    async def aggregate(
        self,
        pipeline: List[xJsonT],
        transaction: Optional[Transaction] = None
    ) -> List[Any]:
        cmd: xJsonT = {
            "aggregate": self.name,
            "pipeline": pipeline,
            "cursor": {}
        }
        request = await self.database.command(cmd, transaction=transaction)
        return request["cursor"]["firstBatch"]

    async def distinct(
        self,
        key: str,
        filter: Optional[xJsonT] = None,
        collation: Optional[xJsonT] = None,
        comment: Optional[str] = None,
        transaction: Optional[Transaction] = None
    ) -> List[Any]:
        command = filter_non_null({
            "distinct": self.name,
            "key": key,
            "query": filter or {},
            "collation": collation,
            "comment": comment
        })
        request = await self.database.command(command, transaction=transaction)
        return request["values"]

    async def count(
        self,
        query: Optional[xJsonT] = None,
        limit: int = 0,
        skip: int = 0,
        hint: Optional[str] = None,
        collation: Optional[xJsonT] = None,
        comment: Optional[str] = None,
        transaction: Optional[Transaction] = None
    ) -> int:
        if not query:
            query = {}
        command = filter_non_null({
            "count": self.name,
            "query": query,
            "limit": limit,
            "skip": skip,
            "hint": hint,
            "collation": collation,
            "comment": comment
        })
        request = await self.database.command(command, transaction=transaction)
        return request["n"]

    async def convert_to_capped(
        self,
        size: int,
        comment: Optional[str] = None
    ) -> None:
        if size <= 0:
            raise Exception("Cannot set size below zero.")
        command = filter_non_null({
            "convertToCapped": self.name,
            "size": size,
            "comment": comment
        })
        await self.database.command(command)

    # https://www.mongodb.com/docs/manual/reference/command/createIndexes/
    async def create_indexes(
        self,
        indexes: List[Index],
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

    # https://www.mongodb.com/docs/manual/reference/command/listIndexes/#listindexes
    async def list_indexes(self) -> List[Index]:
        r = await self.database.command({"listIndexes": self.name})
        info = r["cursor"]["firstBatch"]
        return [Index(
            name=idx["name"],
            keys=list(idx["key"]),
            unique=idx.get("unique", False),
            hidden=idx.get("hidden", False)
        ) for idx in info]

    # https://www.mongodb.com/docs/manual/reference/command/reIndex/
    async def re_index(self) -> None:
        await self.database.command({"reIndex": self.name})

    # https://www.mongodb.com/docs/manual/reference/command/dropIndexes/#dropindexes
    async def drop_indexes(
        self,
        indexes: Optional[Union[str, List[str]]] = None,
        drop_all: bool = False
    ) -> None:
        if drop_all and indexes is None:
            indexes = "*"
        await self.database.command({
            "dropIndexes": self.name,
            "index": indexes
        })
