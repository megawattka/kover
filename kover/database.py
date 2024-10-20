from typing import List, Optional

from .socket import MongoSocket
from .collection import Collection
from .typings import xJsonT
from .session import Transaction

class Database:
    def __init__(self, name: str, socket: MongoSocket) -> None:
        self.name = name
        self.socket = socket

    def get_collection(self, name: str) -> Collection:
        return Collection(name=name, database=self)
    
    def __getattr__(self, name: str) -> Collection:
        return self.get_collection(name=name)
    
    async def collection_names(self) -> List[str]:
        request = await self.socket.request({"listCollections": 1.0}, db_name=self.name)
        return [x["name"] for x in request["cursor"]["firstBatch"]]

    async def create_collection(self, name: str, params: Optional[xJsonT] = None) -> Collection:
        await self.socket.request({
            "create": name, **(params or {})
        }, db_name=self.name)
        return self.get_collection(name)

    async def drop_collection(self, name: str) -> bool:
        request = await self.socket.request({
            "drop": name
        }, db_name=self.name)
        return request["ok"] == 1.0
    
    async def command(self, doc: xJsonT, transaction: Optional[Transaction] = None) -> xJsonT:
        return await self.socket.request(doc=doc, transaction=transaction, db_name=self.name)