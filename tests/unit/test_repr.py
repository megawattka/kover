from unittest.mock import MagicMock

from kover import AuthCredentials, Kover
from kover.network.pool import ConnectionPool
from kover.network.transport import Transport
from kover.session import Session


def test_representations_are_offline_and_do_not_expose_passwords() -> None:
    credentials = AuthCredentials(username="user", password="secret-value")
    pool = MagicMock(spec=ConnectionPool)
    client = Kover(pool=pool)
    database = client.get_database("test")
    collection = database.get_collection("items")
    session = Session({"id": "logical"}, client)
    for instance in (
        client,
        database,
        collection,
        session,
        credentials,
        collection.find(),
        Transport("localhost", 27017),
    ):
        assert repr(instance)
        assert "secret-value" not in repr(instance)
    assert "items" in repr(collection)
    assert "test" in repr(database)
    pool.request.assert_not_awaited()
