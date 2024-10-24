import asyncio
from enum import Enum
from typing import Optional

from kover.auth import AuthCredentials
from kover.client import Kover
from kover.schema import SchemaGenerator, Document, field

class UserType(Enum): 
    ADMIN = "ADMIN"
    USER = "USER"
    CREATOR = "CREATOR"

# can be used as annotation too
class Friend(Document):
    name: str
    age: int = field(min=18)  # minimum age is 18. less will raise ValidationError

# note field_name kwarg in user_type field. it'll be name of that key when using .to_dict()
class User(Document):
    name: str = field(description="must be a string")
    age: int = field(description="age must be int and more that 18", min=18)
    user_type: UserType = field(description="can only be one of the enum values", field_name="userType")
    friend: Optional[Friend]

async def main():
    credentials = AuthCredentials.from_environ() # remove this if no auth present
    kover = await Kover.make_client(credentials=credentials)

    generator = SchemaGenerator()
    schema = generator.generate(User)

    collection_names = [x.name for x in await kover.db.list_collections()]
    if "test" not in collection_names: # collection doesn't exists
        await kover.db.create_collection("test")
    await kover.db.test.set_validator(schema)

    valid_user = User("John Doe", 20, UserType.USER, friend=Friend("dima", 18))
    object_id = await kover.db.test.add_one(valid_user) # specify either model or model.to_dict()
    print(object_id, "added!")

    invalid_user = User("Rick", age=15, user_type=UserType.ADMIN, friend=Friend("roma", 25))
    await kover.db.test.add_one(invalid_user) # kover.exceptions.ErrDocumentValidationFailure: Rick's age is less than 18

if __name__ == "__main__":
    asyncio.run(main())