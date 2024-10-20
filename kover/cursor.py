from __future__ import annotations

import sys
import itertools
if sys.version_info < (3, 11):
    from typing_extensions import Self
else:
    from typing import Self
from collections import deque
from typing import TYPE_CHECKING, Optional, List

from bson import Int64

from .typings import xJsonT

if TYPE_CHECKING:
    from .collection import Collection

class Cursor:
    def __init__(
        self, 
        filter: xJsonT,
        collection: Collection
    ) -> None:
        self._id: Optional[Int64] = None
        self._collection = collection
        self._limit = 0
        self._filter = filter
        self._projection: xJsonT = {"_id": 0} # remove _id
        self._sort: Optional[xJsonT] = None
        self._skip: int = 0
        self._limit: int = 0
        self._batch_size: int = 101
        self._comment: Optional[str] = None
        self._retrieved: int = 0
        self._killed: bool = False
        self._second_iteration: bool = False
        self._docs: deque[xJsonT] = deque()
    
    async def __aenter__(self) -> Self:
        return self

    async def __aexit__(self, *exc) -> None:
        await self.close()

    def sort(self, mapping: xJsonT) -> Self:
        self._sort = mapping
        return self

    def skip(self, value: int) -> Self:
        self._skip = value
        return self
    
    def limit(self, value: int) -> Self:
        self._limit = value
        return self
    
    def batch_size(self, value: int) -> Self:
        self._batch_size = value
        return self
    
    def projection(self, mapping: xJsonT) -> Self:
        self._projection = mapping
        return self
    
    def comment(self, comment: str) -> Self:
        self._comment = comment
        return self
    
    def get_query(self) -> xJsonT:
        command = {
            "find": self._collection.name,
            "filter": self._filter, 
            "skip": self._skip, 
            "limit": self._limit, 
            "projection": self._projection,
            "sort": self._sort,
            "batchSize": self._batch_size,
            "comment": self._comment
        }
        return {k: v for k, v in command.items() if v is not None}
    
    def __aiter__(self) -> Self:
        return self

    async def __anext__(self) -> xJsonT:
        if self._docs:
            return self._docs.popleft()
        if self._id is None:
            query = self.get_query()
            request = await self._collection.database.command(query)
            docs = request["cursor"]["firstBatch"]
            self._retrieved += len(docs)
            self._id = request["cursor"]["id"]
            self._docs.extend(docs)
        else:
            if int(self._id) == 0 or self._second_iteration:
                await self.close()
                raise StopAsyncIteration
            self._second_iteration = True
            command = {
                "getMore": Int64(self._id),
                "collection": self._collection.name
            }
            request = await self._collection.database.command(command)
            docs = request["cursor"]["nextBatch"]
            self._retrieved += len(docs)
            self._docs.extend(docs)
        if self._docs:
            return self._docs.popleft()
        raise StopAsyncIteration

    async def close(self) -> None:
        if not self._killed:
            self._killed = True
            if self._id is not None and int(self._id) > 0 and self._limit != 0:
                command = {"killCursors": self._collection.name, "cursors": [self._id]}
                await self._collection.database.command(command)
            self._docs.clear()

    async def to_list(self) -> List[xJsonT]:
        return [doc async for doc in self]
        