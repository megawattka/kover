import asyncio

from bson import ObjectId

from kover import (
    Kover,
    Document,
    Update,
    Delete,
    AuthCredentials
)


class User(Document):
    name: str
    age: int


async def main():
    credentials = AuthCredentials.from_environ()
    kover = await Kover.make_client(credentials=credentials)

    collection = kover.db.get_collection("test")
    user = User(name="John", age=23)
    file_id: ObjectId = await collection.insert(user)  # or user.to_dict()

    # this concept requires using "$set" explicitly
    # if you dont specify it your entire doc will be
    # just replaced fully to specified here
    # advancements of this way is that you can do anything here not only "$set"
    # e.g {"$push": {"userIds": 12345}} and more
    # in conclusion: be careful with specifying "$set", dont forget it!
    update = Update({"_id": file_id}, {"$set": {"name": "Wick"}})
    await collection.update(update)

    # limit 1 corresponds to .delete_one and 0 to .delete_many
    delete = Delete({"_id": file_id}, limit=1)
    n = await collection.delete(delete)
    print(f"documents deleted: {n}")  # 1


if __name__ == "__main__":
    asyncio.run(main())
