from hashlib import sha1
import logging
import os

from kover.gridfs import GridFS
from kover.gridfs.exceptions import GridFSFileNotFound
from tests.integration.base import MongoTestCase

log = logging.getLogger(__name__)
logging.basicConfig(level=logging.INFO)


class GridFSIntegrationTests(MongoTestCase):
    def __init__(self, *args: str) -> None:
        self._9_mb = 1 * 1024 * 1024 * 9
        super().__init__(*args)

    async def test_gridfs(self) -> None:
        fs = await GridFS(self.database).indexed()
        payload = os.urandom(self._9_mb)
        file_id = await fs.put(payload)
        file, binary = await fs.get_by_file_id(file_id)
        assert file.metadata["sha1"] == sha1(payload).hexdigest()
        assert len(binary.getvalue()) == self._9_mb

    async def test_large_file_roundtrip_and_delete(self) -> None:
        fs = await GridFS(self.database).indexed()
        data = b"gridfs-test-" * (18 * 1024 * 1024 // 12 + 1)
        file_id = await fs.put(data, filename="large.bin")

        file, binary = await fs.get_by_file_id(file_id)
        assert binary.getvalue() == data
        assert file.length == len(data)
        assert file.metadata["sha1"] == sha1(data).hexdigest()

        assert await fs.exists(file_id)
        by_name, _ = await fs.get_by_filename("large.bin")
        assert by_name.object_id == file_id
        assert len(await fs.list()) == 1
        assert await fs.delete(file_id)

        assert not await fs.exists(file_id)
        chunks = self.database.get_collection("fs.chunks")
        assert await chunks.count() == 0
        assert not await fs.delete(file_id)

        with self.assertRaises(GridFSFileNotFound):
            await fs.get_by_file_id(file_id)
