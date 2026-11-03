"""Example of using transactions with Kover."""

import asyncio
import logging
from typing import TYPE_CHECKING

from bson import ObjectId

from kover import AuthCredentials, Kover
from kover.exceptions import OperationFailure

if TYPE_CHECKING:
    from kover import DictT

log = logging.getLogger(__name__)
logging.basicConfig(level=logging.INFO)


async def main() -> None:
    """Entrypoint."""
    credentials = AuthCredentials.from_environ()
    client = await Kover.make_client(credentials=credentials)
    session = await client.start_session()

    # specify _id directly
    doc: DictT = {"_id": ObjectId(), "name": "John", "age": 30}
    collection = await client.db.test.create_if_not_exists()
    try:
        session.start_transaction()
        await collection.insert_one(doc, session=session)

        # it should error with duplicate key now
        await collection.insert_one(doc, session=session)
        await session.commit_transaction()
    except OperationFailure as exc:
        log.info("Got error: %s", exc)
        log.info("%s, %s", exc, type(exc))

        log.info("Transaction failed in session: %s", session)
        await session.abort_transaction()

    found = await collection.find().to_list()
    log.info("documents found: %s", found)  # no documents found due to abort


if __name__ == "__main__":
    asyncio.run(main())
