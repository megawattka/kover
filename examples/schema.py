import asyncio
from enum import Enum
from typing import Optional

from kover.client import Kover
from kover.schema import SchemaGenerator, Document, field


class UserType(Enum):
    ADMIN = "ADMIN"
    USER = "USER"
    CREATOR = "CREATOR"


# can be used as annotation too
class Friend(Document):
    name: str
    age: int = field(min=18)  # minimum age is 18. less will error


# note field_name kwarg in user_type field.
# it'll be name of that key when using .to_dict()
class User(Document):
    name: str = field(description="must be a string")
    age: int = field(
        description="age must be int and more that 18", min=18
    )
    user_type: UserType = field(
        description="can only be one of the enum values",
        field_name="userType"
    )
    friend: Optional[Friend]


async def main():
    kover = await Kover.make_client()

    generator = SchemaGenerator()
    schema = generator.generate(User)

    collection = await kover.db.test.create_if_not_exists()
    await collection.set_validator(schema)

    valid_user = User("John Doe", 20, UserType.USER, friend=Friend("dima", 18))

    # function accepts either valid_user or valid_user.to_dict()
    object_id = await collection.insert_one(valid_user)
    print(object_id, "added!")

    invalid_user = User(
        "Rick",
        age=15,
        user_type=UserType.ADMIN,
        friend=Friend("roma", 25)
    )
    # kover.exceptions.ErrDocumentValidationFailure: Rick's age is less than 18
    await collection.insert_one(invalid_user)

if __name__ == "__main__":
    asyncio.run(main())
