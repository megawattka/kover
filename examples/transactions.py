import asyncio

from bson import ObjectId

from kover.client import Kover
from kover.typings import xJsonT


async def main():
    kover = await Kover.make_client()
    session = await kover.start_session()

    # specify _id directly
    doc: xJsonT = {"_id": ObjectId(), "name": "John", "age": 30}
    collection = await kover.db.test.create_if_not_exists()

    async with session.start_transaction() as transaction:
        await collection.insert(doc, transaction=transaction)
        # it should error with duplicate key now
        await collection.insert(doc, transaction=transaction)

    print(transaction.exception, type(transaction.exception))  # if exist
    print(transaction.state)

    found = await collection.find().to_list()
    print(found)  # no documents found due to transaction abort

if __name__ == "__main__":
    asyncio.run(main())
