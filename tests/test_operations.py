__import__("sys").path.append(
    str(__import__("pathlib").Path(__file__).parent.parent))

import os  # noqa: E402
import unittest  # noqa: E402
from uuid import uuid4, UUID  # noqa: E402

from bson import ObjectId  # noqa: E402

from kover.typings import xJsonT  # noqa: E402
from kover.auth import AuthCredentials  # noqa: E402
from kover.client import Kover  # noqa: E402
from kover.schema import Document  # noqa: E402


class Sample(Document):
    name: str
    age: int
    uuid: UUID

    @classmethod
    def random(cls) -> "Sample":
        return cls(
            os.urandom(4).hex(),
            int.from_bytes(os.urandom(2), "little"),
            uuid4()
        )


class TestMethods(unittest.IsolatedAsyncioTestCase):
    def __init__(self, *args: str, **kwargs: xJsonT) -> None:
        super().__init__(*args, **kwargs)
        self.credentials = AuthCredentials(
            username="main_m1",
            password="incunaby!"
        )
        self.coll_name = "test"

    async def asyncSetUp(self) -> None:
        self.client = await Kover.make_client(credentials=self.credentials)
        assert self.client.signature is not None
        self.addAsyncCleanup(self.client.close)
        self.collection = self.client.db.get_collection(self.coll_name)

    async def asyncTearDown(self) -> None:
        await self.client.db.drop_collection(self.coll_name)

    async def test_insert(self) -> None:
        doc = Sample.random()
        obj_id = await self.collection.insert(doc)
        assert isinstance(obj_id, ObjectId)

        samples = [Sample.random() for _ in range(100)]
        ids = await self.collection.insert(samples)
        assert len(ids) == 100

        count = await self.collection.count()
        assert count == 101

        found = await self.collection.find_one({"name": doc.name}, cls=Sample)
        assert found == doc


if __name__ == "__main__":
    unittest.main()
