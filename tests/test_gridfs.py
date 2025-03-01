__import__("sys").path.append(
    str(__import__("pathlib").Path(__file__).parent.parent))

import os  # noqa: E402
import unittest  # noqa: E402
from uuid import uuid4, UUID  # noqa: E402

from kover.typings import xJsonT  # noqa: E402
from kover.auth import AuthCredentials  # noqa: E402
from kover.client import Kover  # noqa: E402
from kover.schema import Document  # noqa: E402
from kover.gridfs import GridFS  # noqa: E402


class Sample(Document):
    name: str
    age: int
    uuid: UUID

    @classmethod
    def random(cls) -> "Sample":
        return cls.from_args(
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
        print("sha1: ", file.metadata["sha1"])
        assert len(binary.getvalue()) == self._18_mb


if __name__ == "__main__":
    unittest.main()
