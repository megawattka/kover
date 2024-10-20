import asyncio

from bson import ObjectId

from kover.client import Kover
from kover.session import Transaction

async def main():
    kover = await Kover.make_client()
    session = await kover.start_session()
    doc = {"_id": ObjectId(), "name": "John", "age": 30} # specify _id directly
    
    transaction: Transaction
    async with session.start_transaction() as transaction:
        await kover.db.test.add_one(doc, transaction=transaction)
        await kover.db.test.add_one(doc, transaction=transaction) # it should error with duplicate key
    
    print(transaction.exception, type(transaction.exception)) # if exist
    print(transaction.state)

    found = await kover.db.test.find().to_list()
    print(found) # no documents found due to transaction abort

if __name__ == "__main__":
    asyncio.run(main())
