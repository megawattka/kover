from __future__ import annotations

from decimal import Decimal
from enum import IntEnum, StrEnum
from typing import TYPE_CHECKING, Annotated, Any, Literal
from uuid import UUID

from bson import Binary, Decimal128, ObjectId
from pydantic import ConfigDict, Field
import pytest

from kover.schema.document import Document
from kover.schema.generator import MongoDBSchemaGenerator

if TYPE_CHECKING:
    from kover.typings import JsonT


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


class Cat(Document):
    model_config = ConfigDict(extra="forbid")

    kind: Literal["cat"]
    lives: Annotated[int, Field(ge=1, le=9)]


class Dog(Document):
    model_config = ConfigDict(extra="forbid")

    kind: Literal["dog"]
    good: bool


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


class AdvancedUser(Document):
    model_config = ConfigDict(extra="forbid")

    nullable_value: int | None = Field(default=None, alias="nullableValue")
    scalar_union: int | str = Field(alias="scalarUnion")
    fixed_tuple: tuple[str, int] = Field(alias="fixedTuple")
    variadic_tuple: tuple[int, ...] = Field(alias="variadicTuple")
    nullable_items: list[int | None] = Field(alias="nullableItems")
    cats_or_dogs: Cat | Dog = Field(alias="catsOrDogs")


def mongodb_schema(model: type[Document]) -> JsonT:
    return model.model_mongodb_schema()


def get_root_schema(model: type[Document]) -> JsonT:
    schema = mongodb_schema(model)
    root = schema.get("$jsonSchema")

    assert isinstance(root, dict)
    return root  # pyright: ignore[reportUnknownVariableType]


def schema_type(schema: dict[str, Any]) -> str | list[str] | None:
    value: list[str] | str | None = schema.get("bsonType")

    if value is None:
        return None

    assert isinstance(value, (str, list))

    if isinstance(value, list):
        assert all(isinstance(item, str) for item in value)
        return value

    return value


def walk_schema(
    value: dict[str, Any] | list[str] | str,
    path: str = "$",
) -> list[tuple[str, dict[str, Any]]]:
    result: list[tuple[str, dict[str, Any]]] = []

    if isinstance(value, dict):
        result.append((path, value))

        for key, child in value.items():
            child_path = f"{path}.{key}"

            if isinstance(child, (dict, list)):
                result.extend(walk_schema(child, child_path))  # pyright: ignore[reportUnknownArgumentType]

    elif isinstance(value, list):
        for index, child in enumerate(value):
            result.extend(walk_schema(child, f"{path}[{index}]"))

    return result


def assert_no_json_schema_refs(schema: dict[str, Any]) -> None:
    for path, node in walk_schema(schema):
        assert "$ref" not in node, f"{path}: $ref is not supported by MongoDB"
        assert "$defs" not in node, f"{path}: $defs is not supported by MongoDB"  # ruff: ignore[line-too-long]


def assert_no_json_schema_type(schema: dict[str, Any]) -> None:
    for path, node in walk_schema(schema):
        if "bsonType" in node:
            assert "type" not in node, (
                f"{path}: node contains both 'type' and 'bsonType'"
            )


def assert_mongodb_bson_types(schema: dict[str, Any]) -> None:
    allowed_types = {
        "double",
        "string",
        "object",
        "array",
        "binData",
        "undefined",
        "objectId",
        "bool",
        "date",
        "null",
        "regex",
        "dbPointer",
        "javascript",
        "symbol",
        "javascriptWithScope",
        "int",
        "timestamp",
        "long",
        "decimal",
        "minKey",
        "maxKey",
    }

    for path, node in walk_schema(schema):
        if "bsonType" not in node:
            continue

        value: list[str] | str = node["bsonType"]
        values = value if isinstance(value, list) else [value]

        assert values, f"{path}: bsonType must not be empty"

        for bson_type in values:
            assert bson_type in allowed_types, (
                f"{path}: unsupported BSON type {bson_type!r}"
            )


def assert_no_draft_2020_exclusive_limits(schema: dict[str, Any]) -> None:
    for path, node in walk_schema(schema):
        if "exclusiveMinimum" in node:
            assert node["exclusiveMinimum"] is True, (
                f"{path}: MongoDB expects boolean exclusiveMinimum"
            )
            assert "minimum" in node, (
                f"{path}: exclusiveMinimum requires minimum"
            )

        if "exclusiveMaximum" in node:
            assert node["exclusiveMaximum"] is True, (
                f"{path}: MongoDB expects boolean exclusiveMaximum"
            )
            assert "maximum" in node, (
                f"{path}: exclusiveMaximum requires maximum"
            )


def test_user_schema_has_mongodb_root() -> None:
    schema = mongodb_schema(User)

    assert set(schema) == {"$jsonSchema"}
    assert isinstance(schema["$jsonSchema"], dict)


def test_user_root_schema_is_object() -> None:
    root = get_root_schema(User)

    assert schema_type(root) in ("object", ["object"])
    assert root["additionalProperties"] is False


def test_root_id_is_required() -> None:
    root = get_root_schema(User)

    properties = root["properties"]
    required = root["required"]

    assert isinstance(properties, dict)
    assert isinstance(required, list)

    assert "_id" in properties
    assert properties["_id"] == {
        "bsonType": "objectId",
    }
    assert "_id" in required


def test_nested_documents_do_not_receive_id() -> None:
    root = get_root_schema(User)
    properties: JsonT = root["properties"]

    assert isinstance(properties, dict)

    friend: JsonT = properties["friend"]
    assert isinstance(friend, dict)

    any_of: JsonT = friend["anyOf"]
    assert isinstance(any_of, list)

    friend_object = next(
        branch
        for branch in any_of
        if isinstance(branch, dict) and "properties" in branch
    )

    friend_properties = friend_object["properties"]  # pyright: ignore[reportArgumentType]
    friend_required = friend_object["required"]  # pyright: ignore[reportArgumentType]

    assert isinstance(friend_properties, dict)
    assert isinstance(friend_required, list)

    assert "_id" not in friend_properties
    assert "_id" not in friend_required


def test_string_field_is_converted_to_bson_string() -> None:
    root = get_root_schema(User)
    properties: JsonT = root["properties"]

    assert isinstance(properties, dict)

    name: JsonT = properties["name"]
    assert isinstance(name, dict)

    assert schema_type(name) == "string"
    assert name["description"] == "User name"


def test_integer_field_is_converted_to_int_or_long() -> None:
    root = get_root_schema(User)
    properties: JsonT = root["properties"]

    assert isinstance(properties, dict)

    age: JsonT = properties["age"]
    assert isinstance(age, dict)

    assert schema_type(age) == ["int", "long"]


def test_integer_gt_constraint_uses_mongodb_draft_4_format() -> None:
    root = get_root_schema(User)
    properties: JsonT = root["properties"]

    assert isinstance(properties, dict)

    age: JsonT = properties["age"]
    assert isinstance(age, dict)

    assert age["minimum"] == 18
    assert age["exclusiveMinimum"] is True


def test_enum_schema_is_generated() -> None:
    root = get_root_schema(User)
    properties: JsonT = root["properties"]

    assert isinstance(properties, dict)

    user_type: JsonT = properties["userType"]
    assert isinstance(user_type, dict)

    assert schema_type(user_type) == "string"
    assert user_type["enum"] == ["ADMIN", "USER", "CREATOR"]


def test_integer_enum_schema_is_generated() -> None:
    root = get_root_schema(User)
    properties: JsonT = root["properties"]

    assert isinstance(properties, dict)

    priority = properties["priority"]
    assert isinstance(priority, dict)

    assert priority["enum"] == [1, 2, 3]


def test_mixed_literal_does_not_get_invalid_single_bson_type() -> None:
    root = get_root_schema(User)
    properties: JsonT = root["properties"]

    assert isinstance(properties, dict)

    mixed_literal = properties["mixedLiteral"]
    assert isinstance(mixed_literal, dict)

    assert mixed_literal == {"anyOf": [{
        "enum": ["auto", 1],
    }, {"bsonType": "null"}]}
    assert "bsonType" not in mixed_literal


def test_nullable_nested_document_uses_any_of() -> None:
    root = get_root_schema(User)
    properties: JsonT = root["properties"]

    assert isinstance(properties, dict)

    friend: JsonT = properties["friend"]
    assert isinstance(friend, dict)

    any_of: JsonT = friend["anyOf"]
    assert isinstance(any_of, list)
    assert len(any_of) == 2

    null_branches = [
        branch
        for branch in any_of
        if isinstance(branch, dict) and branch.get("bsonType") == "null"  # pyright: ignore[reportUnknownMemberType]
    ]

    assert len(null_branches) == 1


def test_nullable_default_is_not_required() -> None:
    root = get_root_schema(User)
    required = root["required"]

    assert isinstance(required, list)
    assert "friend" not in required


def test_required_non_nullable_fields_are_required() -> None:
    root = get_root_schema(User)
    required: JsonT = root["required"]

    assert isinstance(required, list)

    expected = {
        "name",
        "age",
        "userType",
        "priority",
        "address",
        "tags",
        "scores",
        "attributes",
        "addresses",
        "mixedLiteral",
        "anyValue",
        "data",
        "identifier",
        "amount",
        "_id",
    }

    assert expected.issubset(set(required))
    assert "friend" not in required


def test_any_field_has_empty_schema() -> None:
    root = get_root_schema(User)
    properties = root["properties"]

    assert isinstance(properties, dict)
    assert properties["anyValue"] == {}


def test_bytes_and_uuid_are_binary() -> None:
    root = get_root_schema(User)
    properties: JsonT = root["properties"]

    assert isinstance(properties, dict)

    data: str = properties["data"]
    identifier: Binary = properties["identifier"]

    assert isinstance(data, dict)
    assert isinstance(identifier, dict)

    assert schema_type(data) == "binData"
    assert schema_type(identifier) == "binData"


def test_decimal_is_bson_decimal() -> None:
    root = get_root_schema(User)
    properties: JsonT = root["properties"]

    assert isinstance(properties, dict)

    amount: Decimal = properties["amount"]
    assert isinstance(amount, dict)

    assert schema_type(amount) == "decimal"


def test_dict_of_integers_uses_additional_properties_schema() -> None:
    root = get_root_schema(User)
    properties: JsonT = root["properties"]

    assert isinstance(properties, dict)

    attributes: JsonT = properties["attributes"]
    assert isinstance(attributes, dict)

    additional_properties: JsonT = attributes["additionalProperties"]
    assert isinstance(additional_properties, dict)

    assert schema_type(additional_properties) == ["int", "long"]


def test_dict_of_models_uses_additional_properties_schema() -> None:
    root = get_root_schema(User)
    properties: JsonT = root["properties"]

    assert isinstance(properties, dict)

    addresses: JsonT = properties["addresses"]
    assert isinstance(addresses, dict)

    additional_properties: JsonT = addresses["additionalProperties"]
    assert isinstance(additional_properties, dict)

    assert schema_type(additional_properties) in ("object", ["object"])
    assert "properties" in additional_properties
    assert "required" in additional_properties


def test_array_of_integers_uses_items_schema() -> None:
    root = get_root_schema(User)
    properties: JsonT = root["properties"]

    assert isinstance(properties, dict)

    scores: JsonT = properties["scores"]
    assert isinstance(scores, dict)

    assert schema_type(scores) == "array"

    items: JsonT = scores["items"]
    assert isinstance(items, dict)

    assert schema_type(items) == ["int", "long"]


def test_fixed_tuple_is_converted_to_mongodb_array() -> None:
    root = get_root_schema(AdvancedUser)
    properties: JsonT = root["properties"]

    assert isinstance(properties, dict)

    fixed_tuple: JsonT = properties["fixedTuple"]
    assert isinstance(fixed_tuple, dict)

    assert schema_type(fixed_tuple) == "array"
    assert "prefixItems" not in fixed_tuple
    assert "items" in fixed_tuple

    items: list[str] = fixed_tuple["items"]
    assert isinstance(items, list)
    assert len(items) == 2


def test_variadic_tuple_is_converted_to_mongodb_array() -> None:
    root = get_root_schema(AdvancedUser)
    properties: JsonT = root["properties"]

    assert isinstance(properties, dict)

    variadic_tuple: JsonT = properties["variadicTuple"]
    assert isinstance(variadic_tuple, dict)

    assert schema_type(variadic_tuple) == "array"
    assert "items" in variadic_tuple


def test_all_generated_nodes_use_mongodb_types() -> None:
    root = get_root_schema(User)

    assert_mongodb_bson_types(root)
    assert_no_json_schema_type(root)
    assert_no_json_schema_refs(root)
    assert_no_draft_2020_exclusive_limits(root)


def test_schema_generation_is_repeatable() -> None:
    first = mongodb_schema(User)
    second = mongodb_schema(User)

    assert first == second


def test_serialization_mode_is_rejected() -> None:
    with pytest.raises(ValueError, match="validation"):
        User.model_json_schema(
            mode="serialization",
            schema_generator=MongoDBSchemaGenerator,
        )


def test_bson_values_can_be_constructed_for_integration_tests() -> None:
    binary = Binary(b"payload")
    uuid_binary = Binary(bytes(range(16)))
    decimal = Decimal128(Decimal("12.50"))

    assert isinstance(binary, Binary)
    assert isinstance(uuid_binary, Binary)
    assert isinstance(decimal, Decimal128)


def test_object_id_is_a_valid_bson_value() -> None:
    object_id = ObjectId()

    assert isinstance(object_id, ObjectId)
