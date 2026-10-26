"""Example of using transactions with Kover."""

import asyncio
import logging
from typing import TYPE_CHECKING

from bson import ObjectId

from kover import AuthCredentials, Kover
from kover.exceptions import OperationFailure

if TYPE_CHECKING:
    from kover import JsonT

log = logging.getLogger(__name__)
logging.basicConfig(level=logging.INFO)


async def main() -> None:
    """Entrypoint."""
    credentials = AuthCredentials.from_environ()
    client = await Kover.make_client(credentials=credentials)
    session = await client.start_session()

    # specify _id directly
    doc: JsonT = {"_id": ObjectId(), "name": "John", "age": 30}
    collection = await client.db.test.create_if_not_exists()
    try:
        async with session.start_transaction() as transaction:
            await collection.insert_one(doc, transaction=transaction)

            # it should error with duplicate key now
            await collection.insert_one(doc, transaction=transaction)
    except OperationFailure as exc:
        log.info("Got error: %s", exc)
        log.info("%s, %s", exc, type(exc))

        # such try/except's will always have .transaction field
        assert exc.transaction is not None  # ruff: ignore[pytest-assert-in-except]
        log.info("State after transaction: %s", exc.transaction.state)

    found = await collection.find().to_list()
    log.info("documents found: %s", found)  # no documents found due to abort


if __name__ == "__main__":
    asyncio.run(main())
