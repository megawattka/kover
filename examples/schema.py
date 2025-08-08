"""Example of using kover's schema generation.

This example demonstrates how to use built in
kover schema generation mechanism.
"""

import asyncio
from enum import Enum
import logging
from typing import Annotated

from pydantic import ValidationError

from kover import (
    AuthCredentials,
    Document,
    Kover,
    OperationFailure,
    SchemaGenerator,
)
from kover.metadata import SchemaMetadata

log = logging.getLogger(__name__)
logging.basicConfig(level=logging.INFO)


class UserType(Enum):  # noqa: D101
    ADMIN = "ADMIN"
    USER = "USER"
    CREATOR = "CREATOR"


class Friend(Document):  # noqa: D101
    name: str
    age: Annotated[int, SchemaMetadata(minimum=18)]  # minimum age is 18.


# kover automatically generates aliases using camel case.
# so user_type will be "userType" in db
# if you still need to snake cased field_name
# use explicit alias="<snake_cased_name>"
class User(Document):  # noqa: D101
    name: Annotated[str, SchemaMetadata(description="must be a string")]
    age: Annotated[
        int,
        SchemaMetadata(
            description="age must be int and more that 18", minimum=18,
        ),
    ]
    user_type: Annotated[
        UserType,
        SchemaMetadata(description="can only be one of the enum values"),
    ]
    friend: Friend | None


async def main() -> None:
    """Entrypoint."""
    credentials = AuthCredentials.from_environ()
    kover = await Kover.make_client(credentials=credentials)

    generator = SchemaGenerator()
    schema = generator.generate(User)

    collection = await kover.db.test.create_if_not_exists()
    await collection.set_validator(schema)

    valid_user = User(
        name="John Doe",
        age=20,
        user_type=UserType.USER,
        friend=Friend(name="dima", age=18),
    )
    # function accepts either valid_user or valid_user.to_dict()
    object_id = await collection.insert(valid_user)
    log.info(f"{object_id}, added!")

    try:
        invalid_user = User(
            name="Rick",
            age=15,
            user_type=UserType.ADMIN,
            friend=Friend(name="roma", age=25),
        )
    except ValidationError as e:  # it wont let you create such model
        raise SystemExit(e.errors()) from e

    # somehow if you try to insert invalid_user.to_dict()
    # kover.exceptions.ErrDocumentValidationFailure: Rick's age is less than 18
    try:
        await collection.insert(invalid_user)
    except OperationFailure as e:
        msg: str = e.message["errmsg"]
        log.info(f"got Error: {msg}")
        assert e.code == 121  # ErrDocumentValidationFailure  # noqa: E501, PT017


if __name__ == "__main__":
    asyncio.run(main())
