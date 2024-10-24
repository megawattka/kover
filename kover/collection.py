from __future__ import annotations

from typing import (
    List, 
    Optional, 
    TYPE_CHECKING, 
    Any, 
    Type, 
    overload, 
    TypeVar, 
    Union, 
    Sequence
)

from bson import ObjectId

from .typings import xJsonT
from .session import Transaction
from .cursor import Cursor
from .schema import Document, filter_non_null
from .enums import ValidationLevel

if TYPE_CHECKING:
    from .database import Database

T = TypeVar("T")

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

    async def with_options(self) -> Collection:
        infos = await self.database.list_collections({"name": self.name})
        if not infos:
            raise Exception(f'namespace "{self.name}" not found in database "{self.database.name}"')
        return infos[0]

    async def coll_mod(self, params: xJsonT) -> None:
        await self.database.command({
            "collMod": self.name, **params
        })

    async def set_validator(self, validator: xJsonT, level: ValidationLevel = ValidationLevel.MODERATE) -> None:
        await self.coll_mod({"validator": validator, "validationLevel": level.value.lower()})

    async def add_one(
        self, 
        doc: Union[xJsonT, Document],
        transaction: Optional[Transaction] = None
    ) -> ObjectId:
        if isinstance(doc, Document):
            doc = doc.to_dict()
        doc = doc.copy(); doc.setdefault("_id", ObjectId())
        command: xJsonT = {"insert": self.name, "ordered": True, "documents": [doc]}
        await self.database.command(command, transaction=transaction)
        return doc["_id"]

    async def add_many(
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
        command: xJsonT = {"insert": self.name, "ordered": True, "documents": needed}
        await self.database.command(command, transaction=transaction)
        return [doc["_id"] for doc in needed]

    async def update_one(
        self, 
        filter: xJsonT, 
        to_replace: xJsonT,
        upsert: bool = False,
        transaction: Optional[Transaction] = None
    ) -> int:
        command = {"update": self.name, "ordered": True, "updates": [{"q": filter, "u": {"$set": to_replace}, "multi": False, "upsert": upsert}]}
        request = await self.database.command(command, transaction=transaction)
        return request["nModified"]

    async def update_many(
        self, 
        filter: xJsonT, 
        to_replace: xJsonT,
        upsert: bool = False,
        transaction: Optional[Transaction] = None
    ) -> int:
        params = {"update": self.name, "ordered": True, "updates": [{"q": filter, "u": {"$set": to_replace}, "multi": True, "upsert": upsert}]}
        request = await self.database.command(params, transaction=transaction)
        return request["nModified"]

    async def delete_one(
        self, 
        filter: Optional[xJsonT] = None,
        transaction: Optional[Transaction] = None
    ) -> bool:
        params = {"delete": self.name, "ordered": True, "deletes": [{"q": filter or {}, "limit": 1}]}
        request = await self.database.command(params, transaction=transaction)
        return bool(request["n"])

    async def delete_many(
        self, 
        filter: Optional[xJsonT] = None,
        limit: int = 0, 
        transaction: Optional[Transaction] = None
    ) -> int:
        params = {"delete": self.name, "ordered": True, "deletes": [{"q": filter or {}, "limit": limit}]}
        request = await self.database.command(params, transaction=transaction)
        return request["n"]

    @overload
    async def find_one(
        self,
        filter: Optional[xJsonT] = None,
        entity_cls: None = None
    ) -> Optional[xJsonT]:
        ...

    @overload
    async def find_one(
        self,
        filter: Optional[xJsonT] = None,
        entity_cls: Type[T] = ...
    ) -> Optional[T]:
        ...
    
    async def find_one(
        self, 
        filter: Optional[xJsonT] = None,
        entity_cls: Optional[Type[T]] = None
    ) -> Optional[Union[T, xJsonT]]:
        documents = await self.find(filter=filter, entity_cls=entity_cls).limit(1).to_list()
        if documents:
            return documents[0]
        return None

    @overload
    def find(
        self,
        filter: Optional[xJsonT] = None,
        entity_cls: None = ...
    ) -> Cursor[xJsonT]:
        ...

    @overload
    def find(
        self,
        filter: Optional[xJsonT] = None,
        entity_cls: Optional[Type[T]] = None
    ) -> Cursor[T]:
        ...
    
    def find(
        self, 
        filter: Optional[xJsonT] = None,
        entity_cls: Optional[Type[T]] = None
    ) -> Cursor:
        return Cursor(filter=filter or {}, collection=self, entity_cls=entity_cls)

    async def aggregate(self, pipeline: List[xJsonT], transaction: Optional[Transaction] = None):
        cmd = {"aggregate": self.name, "pipeline": pipeline, "cursor": {}}
        request = await self.database.command(cmd, transaction=transaction)
        return request["cursor"]["firstBatch"]
    
    async def distinct(
        self, 
        key: str, 
        filter: Optional[xJsonT] = None,
        collation: Optional[xJsonT] = None,
        comment: Optional[str] = None,
    ) -> List[Any]:
        command = filter_non_null({
            "distinct": self.name, 
            "key": key, 
            "query": filter or {}, 
            "collation": collation, 
            "comment": comment
        })
        request = await self.database.command(command)
        return request["values"]
    
    async def count(
        self, 
        query: Optional[xJsonT] = None, 
        limit: int = 0, 
        skip: int = 0,
        hint: Optional[str] = None,
        collation: Optional[xJsonT] = None,
        comment: Optional[str] = None
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
        request = await self.database.command(command)
        return request["n"]
