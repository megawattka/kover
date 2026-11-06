from __future__ import annotations

from collections.abc import AsyncGenerator
from datetime import UTC, datetime
from decimal import Decimal
from enum import IntEnum, StrEnum
import os
from typing import TYPE_CHECKING, Annotated, Any, Literal
from uuid import UUID, uuid4

from bson import Binary, Decimal128, ObjectId
from pydantic import ConfigDict, Field
import pytest

from kover import AuthCredentials, make_client
from kover.exceptions import OperationFailure
from kover.schema import Document

if TYPE_CHECKING:
    from kover.collection import Collection
    from kover.database import Database


class UserType(StrEnum):
    ADMIN = "ADMIN"
    USER = "USER"
    CREATOR = "CREATOR"


class Priority(IntEnum):
    LOW = 1
    NORMAL = 2
    HIGH = 3


class Address(Document):
    model_config = ConfigDict(extra="forbid")

    city: Annotated[str, Field(min_length=1)]
    postal_code: Annotated[
        str,
        Field(pattern=r"^[0-9]{5}$", alias="postalCode"),
    ]


class Friend(Document):
    model_config = ConfigDict(extra="forbid")

    name: str
    age: Annotated[int, Field(gt=18)]


class User(Document):
    model_config = ConfigDict(extra="forbid")

    name: Annotated[str, Field(description="User name")]
    age: Annotated[
        int,
        Field(gt=18, description="Age must be greater than 18"),
    ]
    user_type: UserType = Field(alias="userType")
    priority: Priority
    friend: Friend | None = None
    address: Address
    tags: list[str]
    scores: list[int]
    attributes: dict[str, int]
    addresses: dict[str, Address]
    mixed_literal: Literal["auto", 1] | None = Field(alias="mixedLiteral")
    any_value: Any = Field(alias="anyValue")
    data: bytes
    identifier: UUID
    amount: Decimal


@pytest.fixture
async def database() -> AsyncGenerator[Database, Any]:
    if os.environ.get("KOVER_RUN_INTEGRATION") != "1":
        pytest.skip("Set KOVER_RUN_INTEGRATION=1 to use a real MongoDB")
    client = await make_client(
        host=os.environ.get("MONGO_HOST", "127.0.0.1"),
        port=int(os.environ.get("MONGO_PORT", "27017")),
        credentials=AuthCredentials.from_environ(),
    )

    async with client:
        await client.admin.ping()
        database_name = f"schema_generator_{uuid4().hex}"

        try:
            yield client.get_database(database_name)
        finally:
            await client.drop_database(database_name)


@pytest.fixture
async def collection(
    database: Database,
) -> AsyncGenerator[Collection, Any]:
    collection_name = f"user_{uuid4().hex}"

    validator = User.model_mongodb_schema()

    collection = await database.create_collection(
        collection_name,
        params={
            "validator": validator,
            "validationLevel": "strict",
            "validationAction": "error",
        },
    )

    options = (await collection.with_options()).options
    assert options is not None
    assert options["validator"] == validator
    assert options["validationLevel"] == "strict"
    assert options["validationAction"] == "error"

    yield collection

    await collection.drop()


def valid_user_document() -> dict[str, Any]:
    return {
        "_id": ObjectId(),
        "name": "Alice",
        "age": 25,
        "userType": "USER",
        "priority": 2,
        "friend": {
            "name": "Bob",
            "age": 30,
        },
        "address": {
            "city": "Paris",
            "postalCode": "75001",
        },
        "tags": ["python", "mongodb"],
        "scores": [10, 20, 30],
        "attributes": {
            "first": 1,
            "second": 2,
        },
        "addresses": {
            "home": {
                "city": "Paris",
                "postalCode": "75001",
            },
        },
        "mixedLiteral": "auto",
        "anyValue": {
            "anything": [
                1,
                "two",
                None,
            ],
        },
        "data": Binary(b"payload"),
        "identifier": Binary(bytes(range(16))),
        "amount": Decimal128(Decimal("12.50")),
    }


async def insert_valid_document(collection: Collection) -> ObjectId:
    document = valid_user_document()
    object_id = await collection.insert_one(document)

    assert isinstance(object_id, ObjectId)
    return object_id


async def assert_document_rejected(
    collection: Collection,
    document: dict[str, Any],
) -> None:
    with pytest.raises(OperationFailure) as error:
        await collection.insert_one(document)

    assert error.value.code == 121


async def test_mongodb_accepts_generated_validator(
    collection: Collection,
) -> None:
    inserted_id = await insert_valid_document(collection)

    stored = await collection.find_one({"_id": inserted_id})

    assert stored is not None
    assert stored["_id"] == inserted_id


async def test_valid_null_friend_is_accepted(
    collection: Collection,
) -> None:
    document = valid_user_document()
    document["friend"] = None

    object_id = await collection.insert_one(document)

    assert isinstance(object_id, ObjectId)


async def test_optional_friend_can_be_omitted(
    collection: Collection,
) -> None:
    document = valid_user_document()
    document.pop("friend")

    object_id = await collection.insert_one(document)

    assert isinstance(object_id, ObjectId)


async def test_missing_required_field_is_rejected(
    collection: Collection,
) -> None:
    document = valid_user_document()
    document.pop("name")

    await assert_document_rejected(collection, document)


async def test_missing_id_is_rejected_or_added_by_mongodb(
    collection: Collection,
) -> None:
    document = valid_user_document()
    document.pop("_id")

    object_id = await collection.insert_one(document)

    assert isinstance(object_id, ObjectId)


async def test_invalid_string_is_rejected(
    collection: Collection,
) -> None:
    document = valid_user_document()
    document["name"] = 123

    await assert_document_rejected(collection, document)


async def test_invalid_integer_is_rejected(
    collection: Collection,
) -> None:
    document = valid_user_document()
    document["age"] = "25"

    await assert_document_rejected(collection, document)


async def test_exclusive_minimum_is_enforced(
    collection: Collection,
) -> None:
    document = valid_user_document()
    document["age"] = 18

    await assert_document_rejected(collection, document)


async def test_integer_long_is_accepted(
    collection: Collection,
) -> None:
    document = valid_user_document()
    document["age"] = 2**40

    object_id = await collection.insert_one(document)

    assert isinstance(object_id, ObjectId)


async def test_invalid_enum_value_is_rejected(
    collection: Collection,
) -> None:
    document = valid_user_document()
    document["userType"] = "INVALID"

    await assert_document_rejected(collection, document)


async def test_invalid_integer_enum_value_is_rejected(
    collection: Collection,
) -> None:
    document = valid_user_document()
    document["priority"] = 99

    await assert_document_rejected(collection, document)


async def test_invalid_nested_document_is_rejected(
    collection: Collection,
) -> None:
    document = valid_user_document()
    document["friend"] = {
        "name": "Bob",
        "age": 18,
    }

    await assert_document_rejected(collection, document)


async def test_nested_document_does_not_require_id(
    collection: Collection,
) -> None:
    document = valid_user_document()
    document["friend"] = {
        "name": "Bob",
        "age": 30,
    }

    object_id = await collection.insert_one(document)

    assert isinstance(object_id, ObjectId)


async def test_extra_root_field_is_rejected(
    collection: Collection,
) -> None:
    document = valid_user_document()
    document["unexpected"] = True

    await assert_document_rejected(collection, document)


async def test_extra_nested_field_is_rejected(
    collection: Collection,
) -> None:
    document = valid_user_document()
    document["address"]["unexpected"] = True

    await assert_document_rejected(collection, document)


async def test_invalid_array_item_is_rejected(
    collection: Collection,
) -> None:
    document = valid_user_document()
    document["scores"] = [1, "2", 3]

    await assert_document_rejected(collection, document)


async def test_invalid_dictionary_value_is_rejected(
    collection: Collection,
) -> None:
    document = valid_user_document()
    document["attributes"] = {
        "valid": 1,
        "invalid": "2",
    }

    await assert_document_rejected(collection, document)


async def test_invalid_dictionary_model_value_is_rejected(
    collection: Collection,
) -> None:
    document = valid_user_document()
    document["addresses"] = {
        "home": {
            "city": "Paris",
            "postal_code": "invalid",
        },
    }

    await assert_document_rejected(collection, document)


async def test_mixed_literal_accepts_string(
    collection: Collection,
) -> None:
    document = valid_user_document()
    document["mixedLiteral"] = "auto"

    object_id = await collection.insert_one(document)

    assert isinstance(object_id, ObjectId)


async def test_mixed_literal_accepts_integer(
    collection: Collection,
) -> None:
    document = valid_user_document()
    document["mixedLiteral"] = 1

    object_id = await collection.insert_one(document)

    assert isinstance(object_id, ObjectId)


async def test_mixed_literal_accepts_null(
    collection: Collection,
) -> None:
    document = valid_user_document()
    document["mixedLiteral"] = None

    object_id = await collection.insert_one(document)

    assert isinstance(object_id, ObjectId)


async def test_mixed_literal_rejects_other_value(
    collection: Collection,
) -> None:
    document = valid_user_document()
    document["mixedLiteral"] = "manual"

    await assert_document_rejected(collection, document)


async def test_any_accepts_string(
    collection: Collection,
) -> None:
    document = valid_user_document()
    document["anyValue"] = "anything"

    object_id = await collection.insert_one(document)

    assert isinstance(object_id, ObjectId)


async def test_any_accepts_array(
    collection: Collection,
) -> None:
    document = valid_user_document()
    document["anyValue"] = [1, "two", None, {"nested": True}]

    object_id = await collection.insert_one(document)

    assert isinstance(object_id, ObjectId)


async def test_any_accepts_null(
    collection: Collection,
) -> None:
    document = valid_user_document()
    document["anyValue"] = None

    object_id = await collection.insert_one(document)

    assert isinstance(object_id, ObjectId)


async def test_bytes_are_stored_as_bindata(
    collection: Collection,
) -> None:
    document = valid_user_document()
    document["data"] = Binary(b"hello")

    object_id = await collection.insert_one(document)
    stored = await collection.find_one({"_id": object_id})

    assert stored is not None
    assert isinstance(stored["data"], Binary)


async def test_uuid_representation_as_bindata(
    collection: Collection,
) -> None:
    document = valid_user_document()
    document["identifier"] = Binary(bytes(range(16)))

    object_id = await collection.insert_one(document)
    stored = await collection.find_one({"_id": object_id})

    assert stored is not None
    assert isinstance(stored["identifier"], Binary)


async def test_decimal128_is_accepted(
    collection: Collection,
) -> None:
    document = valid_user_document()
    document["amount"] = Decimal128("999999999999999999.999")

    object_id = await collection.insert_one(document)
    stored = await collection.find_one({"_id": object_id})

    assert stored is not None
    assert isinstance(stored["amount"], Decimal128)


async def test_string_is_not_accepted_for_decimal(
    collection: Collection,
) -> None:
    document = valid_user_document()
    document["amount"] = "12.50"

    await assert_document_rejected(collection, document)


async def test_datetime_is_not_used_for_decimal_field(
    collection: Collection,
) -> None:
    document = valid_user_document()
    document["amount"] = datetime.now(UTC)

    await assert_document_rejected(collection, document)


async def test_generated_schema_is_used_directly(
    database: Database,
) -> None:
    collection_name = f"direct_schema_{uuid4().hex}"
    validator = User.model_mongodb_schema()

    collection = await database.create_collection(
        collection_name,
        params={"validator": validator},
    )
    try:
        inserted_id = await insert_valid_document(collection)
        assert isinstance(inserted_id, ObjectId)
    finally:
        await collection.drop()
