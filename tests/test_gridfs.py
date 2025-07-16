from __future__ import annotations

import logging
import os
from typing import TYPE_CHECKING
import unittest
from uuid import uuid4

from kover.auth import AuthCredentials
from kover.client import Kover
from kover.gridfs import GridFS
from kover.schema import Document

if TYPE_CHECKING:
    from uuid import UUID

log = logging.getLogger(__name__)
logging.basicConfig(level=logging.INFO)


class Sample(Document):
    name: str
    age: int
    uuid: UUID

    @classmethod
    def random(cls) -> Sample:
        return cls(
            name=os.urandom(4).hex(),
            age=int.from_bytes(os.urandom(2), "little"),
            uuid=uuid4(),
        )


class TestMethods(unittest.IsolatedAsyncioTestCase):
    def __init__(self, *args: str, **kwargs: object) -> None:
        super().__init__(*args, **kwargs)
        self.credentials = AuthCredentials(
            username="main_m1",
            password="incunaby!",
        )
        self.coll_name = "fs"

    async def asyncSetUp(self) -> None:
        self.client = await Kover.make_client(credentials=self.credentials)
        assert self.client.signature is not None
        self.addAsyncCleanup(self.client.close)
        self.collection = self.client.db.get_collection(self.coll_name)
        self._18_mb = 1 * 1024 * 1024 * 18

    async def asyncTearDown(self) -> None:
        await self.client.db.drop_collection(self.coll_name)

    async def test_gridfs(self) -> None:
        fs = await GridFS(self.client.gridfsdb).indexed()
        file_id = await fs.put(os.urandom(self._18_mb))
        file, binary = await fs.get_by_file_id(file_id)
        sha1_hash = file.metadata["sha1"]
        log.info(f"sha1: {sha1_hash}")
        assert len(binary.getvalue()) == self._18_mb


if __name__ == "__main__":
    unittest.main()
