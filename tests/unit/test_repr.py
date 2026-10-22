import unittest

from kover import Kover, MongoTransport


class InvalidUriTests(unittest.IsolatedAsyncioTestCase):
    def __init__(self, *args: ..., **kwargs: ...) -> None:
        super().__init__(*args, **kwargs)
        self.uri = "mongodb://main_m1:incunaby!@localhost:27017?tls=false&maxpoolsize=10"

    async def test_all_reprs(self) -> None:
        client = await Kover.from_uri(self.uri)
        repr(client)
        database = client.get_database("test")
        repr(database)
        collection = database.get_collection("test")
        repr(collection)
        session = await client.start_session()
        repr(session)
        transaction = session.start_transaction()
        repr(transaction)
        transport = MongoTransport("127.0.0.1", 27017, tls=False)
        await transport.connect()
        repr(transport)


if __name__ == "__main__":
    unittest.main()
