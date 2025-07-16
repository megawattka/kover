import asyncio
import logging
from typing import TYPE_CHECKING

from bson import ObjectId

from kover import AuthCredentials, Kover

if TYPE_CHECKING:
    from kover import xJsonT

log = logging.getLogger(__name__)
logging.basicConfig(level=logging.INFO)


async def main() -> None:  # noqa: D103
    credentials = AuthCredentials.from_environ()
    kover = await Kover.make_client(credentials=credentials)
    session = await kover.start_session()

    # specify _id directly
    doc: xJsonT = {"_id": ObjectId(), "name": "John", "age": 30}
    collection = await kover.db.test.create_if_not_exists()

    async with session.start_transaction() as transaction:
        await collection.insert(doc, transaction=transaction)
        # it should error with duplicate key now
        await collection.insert(doc, transaction=transaction)

    exc = transaction.exception  # if exist
    log.info(f"{exc}, {type(exc)}")
    log.info(f"trx state: {transaction.state}")

    found = await collection.find().to_list()
    log.info(found)  # no documents found due to transaction abort


if __name__ == "__main__":
    asyncio.run(main())
