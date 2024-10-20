from __future__ import annotations

from typing import List, Optional, TYPE_CHECKING

from bson import ObjectId

from .typings import xJsonT
from .session import Transaction
from .models import Response
from .cursor import Cursor

if TYPE_CHECKING:
    from .database import Database

class Collection:
    def __init__(self, name: str, database: Database) -> None:
        self.name = name
        self.database = database

    async def count_documents(
        self,
        filter: Optional[xJsonT] = None,
    ) -> int:
        if filter is None:
            filter = {}
        pipeline: List[xJsonT] = [{"$match": filter}, {"$group": {"_id": 1, "n": {"$sum": 1}}}]
        command = {"aggregate": self.name, "pipeline": pipeline, "cursor": {}}
        request = await self.database.socket.request(command, db_name=self.database.name)
        if request["cursor"]["firstBatch"]:
            return request["cursor"]["firstBatch"][0]["n"]
        return 0
    
    async def coll_mod(self, params: xJsonT) -> bool:
        request = await self.database.socket.request({
            "collMod": self.name, **params
        }, db_name=self.database.name)
        return request["ok"] == 1.0

    async def add_one(
        self, 
        doc: xJsonT,
        transaction: Optional[Transaction] = None
    ) -> ObjectId:
        doc = doc.copy(); doc.setdefault("_id", ObjectId())
        command = {"insert": self.name, "ordered": True, "documents": [doc]}
        await self.database.socket.request(command, db_name=self.database.name, transaction=transaction)
        return doc["_id"]

    async def add_many(
        self, 
        docs: List[xJsonT], 
        transaction: Optional[Transaction] = None
    ) -> List[ObjectId]:
        assert len(docs) > 0, "Empty sequence of documents"
        docs = [doc.copy() for doc in docs]
        for doc in docs:
            doc.setdefault("_id", ObjectId())
        command = {"insert": self.name, "ordered": True, "documents": docs}
        await self.database.socket.request(command, db_name=self.database.name, transaction=transaction)
        return [doc["_id"] for doc in docs]

    async def update_one(
        self, 
        filter: xJsonT, 
        to_replace: xJsonT,
        upsert: bool = False,
        transaction: Optional[Transaction] = None
    ) -> Response[int]:
        command = {"update": self.name, "ordered": True, "updates": [{"q": filter, "u": {"$set": to_replace}, "multi": False, "upsert": upsert}]}
        request = await self.database.socket.request(command, db_name=self.database.name, transaction=transaction)
        return Response(request["nModified"])

    async def update_many(
        self, 
        filter: xJsonT, 
        to_replace: xJsonT,
        upsert: bool = False,
        transaction: Optional[Transaction] = None
    ) -> Response[int]:
        params = {"update": self.name, "ordered": True, "updates": [{"q": filter, "u": {"$set": to_replace}, "multi": True, "upsert": upsert}]}
        request = await self.database.socket.request(params, db_name=self.database.name, transaction=transaction)
        return Response(request["nModified"])

    async def delete_one(
        self, 
        filter: xJsonT,
        transaction: Optional[Transaction] = None
    ) -> bool:
        params = {"delete": self.name, "ordered": True, "deletes": [{"q": filter, "limit": 1}]}
        request = await self.database.socket.request(params, db_name=self.database.name, transaction=transaction)
        return bool(request["n"])

    async def delete_many(
        self, 
        filter: xJsonT,
        limit: int = 0, 
        transaction: Optional[Transaction] = None
    ) -> int:
        params = {"delete": self.name, "ordered": True, "deletes": [{"q": filter, "limit": limit}]}
        request = await self.database.socket.request(params, db_name=self.database.name, transaction=transaction)
        return request["n"]

    async def find_one(
        self, 
        filter: Optional[xJsonT] = None
    ) -> Response[xJsonT]:
        request = await self.aggregate([{"$match": filter}, {"$limit": 1}, {"$unset": "_id"}])
        return Response(request[0] if request else request)

    def find(
        self, 
        filter: Optional[xJsonT] = None
    ) -> Cursor:
        if filter is None:
            filter = {}
        return Cursor(filter=filter, collection=self)

    async def aggregate(self, pipeline: List[xJsonT], transaction: Optional[Transaction] = None):
        cmd = {"aggregate": self.name, "pipeline": pipeline, "cursor": {}}
        request = await self.database.socket.request(cmd, db_name=self.database.name, transaction=transaction)
        return request["cursor"]["firstBatch"]