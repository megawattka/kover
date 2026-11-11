import os
import unittest
from uuid import uuid4

from elune import CodecOptions, UuidRepresentation

from kover import AuthCredentials, make_client


@unittest.skipUnless(
    os.environ.get("KOVER_RUN_INTEGRATION") == "1",
    "Set KOVER_RUN_INTEGRATION=1 to use a real MongoDB",
)
class MongoTestCase(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self) -> None:
        codec_options = CodecOptions(
            uuid_representation=UuidRepresentation.STANDARD,
        )
        self.client = await make_client(
            host=os.environ.get("MONGO_HOST", "127.0.0.1"),
            port=int(os.environ.get("MONGO_PORT", "27017")),
            credentials=AuthCredentials.from_environ(),
            codec_options=codec_options,
        )
        self.addAsyncCleanup(self.client.close)
        name = "kover_test_" + uuid4().hex
        self.addAsyncCleanup(self.client.drop_database, name)
        self.database = self.client.get_database(name)
