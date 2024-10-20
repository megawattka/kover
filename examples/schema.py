import asyncio
from enum import Enum

from attrs import define, field

from kover import Kover
from kover.schema import SchemaGenerator, Document

class UserType(Enum): 
    ADMIN = "ADMIN"
    USER = "USER"
    CREATOR = "CREATOR"

@define # entities must be annotated with @define
class User(Document): # and subclassed from kover.schema.Document
    name: str = field(metadata={"description": "must be a string and is required"})
    age: int = field(metadata={"min": 18, "description": "age must be int and more that 18"})
    user_type: UserType = field(metadata={"description": "can only be one of the enum values and is not required", "fieldName": "userType"})

@define # subdocument
class Friend: # must not subclassed from kover.schema.Document
    name: str
    description: str
# now it can be used as annotation

### note fieldName in user_type metadata. it will be key of that attribute when using .to_dict()

async def main():
    kover = await Kover.make_client()
    generator = SchemaGenerator()
    schema = generator.generate(User)

    await kover.db.create_collection("test")
    await kover.db.test.coll_mod({"validator": schema, "validationLevel": "moderate"})
    # can be one-lined to await kover.db.create_collection("test", {"validator": schema, "validationLevel": "moderate"})

    valid_user = User("John Doe", 20, UserType.USER)
    object_id = await kover.db.test.add_one(valid_user.to_dict())
    print(object_id, "added!")

    invalid_user = User("Rick", 15, UserType.ADMIN)
    await kover.db.test.add_one(invalid_user.to_dict()) # Error: age is less than 18

if __name__ == "__main__":
    asyncio.run(main())