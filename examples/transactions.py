import asyncio

from bson import ObjectId

from kover.client import Kover
from kover.session import Transaction


async def main():
    kover = await Kover.make_client()
    session = await kover.start_session()

    # specify _id directly
    doc = {"_id": ObjectId(), "name": "John", "age": 30}

    transaction: Transaction
    async with session.start_transaction() as transaction:
        await kover.db.test.add_one(doc, transaction=transaction)
        # it should error with duplicate key now
        await kover.db.test.add_one(doc, transaction=transaction)

    print(transaction.exception, type(transaction.exception))  # if exist
    print(transaction.state)

    found = await kover.db.test.find().to_list()
    print(found)  # no documents found due to transaction abort

if __name__ == "__main__":
    asyncio.run(main())
