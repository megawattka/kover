"""Example of using kover's schema generation.

This example demonstrates how to use built in
kover schema generation mechanism.
"""

import asyncio
from enum import Enum
import logging
from typing import Annotated

from pydantic import Field, ValidationError

from kover import (
    AuthCredentials,
    Document,
    Kover,
    OperationFailure,
)

log = logging.getLogger(__name__)
logging.basicConfig(level=logging.INFO)


class UserType(Enum):  # ruff: ignore[undocumented-public-class]
    ADMIN = "ADMIN"
    USER = "USER"
    CREATOR = "CREATOR"


class Friend(Document):  # ruff: ignore[undocumented-public-class]
    name: str
    age: Annotated[int, Field(ge=18)]  # minimum age is 18.


# kover automatically generates aliases using camel case.
# so user_type will be "userType" in db
# if you still need to snake cased field_name
# use explicit alias="<snake_cased_name>"
class User(Document):  # ruff: ignore[undocumented-public-class]
    name: Annotated[str, Field(description="must be a string")]
    age: Annotated[
        int,
        Field(description="age must be int and more that 18", ge=18),
    ]
    user_type: Annotated[
        UserType,
        Field(description="can only be one of the enum values"),
    ]
    friend: Friend | None


async def main() -> None:
    """Entrypoint.

    Raises:
        OperationFailure: If insertion fails for an unexpected reason.
    """
    credentials = AuthCredentials.from_environ()
    client = await Kover.make_client(credentials=credentials)

    schema = User.model_mongodb_schema()

    collection = await client.db.test.create_if_not_exists()
    await collection.set_validator(schema)

    valid_user = User(
        name="John Doe",
        age=20,
        user_type=UserType.USER,
        friend=Friend(name="dima", age=18),
    )
    # function accepts either valid_user or valid_user.to_dict()
    object_id = await collection.insert_one(valid_user)
    log.info("%s, added!", object_id)

    try:
        User(
            name="Rick",
            age=15,
            user_type=UserType.ADMIN,
            friend=Friend(name="roma", age=25),
        )
    except ValidationError as e:  # it wont let you create such model
        log.info("%s", e)

    # somehow if you try to insert invalid object
    # kover.exceptions.ErrDocumentValidationFailure: Rick's age is less than 18
    try:
        invalid = {
            "name": "Rick",
            "age": 15,
            "user_type": "ADMIN",
            "friend": {"name": "roma", "age": 25},
        }
        await collection.insert_one(invalid)
    except OperationFailure as e:
        if e.code != 121:  # ErrDocumentValidationFailure  # ruff: ignore[magic-value-comparison]
            raise
        log.info("got Error: %s, %s", e.__class__, e)

    await client.db.drop_collection("test")


if __name__ == "__main__":
    asyncio.run(main())
