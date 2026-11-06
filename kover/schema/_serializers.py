"""Serializers for kover schema."""

from __future__ import annotations

from typing import TYPE_CHECKING, Any
from uuid import UUID

if TYPE_CHECKING:
    from bson import Binary, Decimal128, Int64, ObjectId, Regex, Timestamp
    from pydantic import GetJsonSchemaHandler
    from pydantic_core import CoreSchema


def validate_uuid(value: UUID | Binary) -> UUID:
    if isinstance(value, UUID):
        return value

    return value.as_uuid()


def bin_data_json_schema(
    _cls: type[UUID | Binary],
    _core_schema: CoreSchema,
    _handler: GetJsonSchemaHandler,
) -> dict[str, Any]:
    return {"bsonType": "binData"}


def object_id_json_schema(
    _cls: type[ObjectId],
    _core_schema: CoreSchema,
    _handler: GetJsonSchemaHandler,
) -> dict[str, Any]:
    return {"bsonType": "objectId"}


def long_json_schema(
    _cls: type[Int64],
    _core_schema: CoreSchema,
    _handler: GetJsonSchemaHandler,
) -> dict[str, Any]:
    return {"bsonType": "long"}


def decimal_json_schema(
    _cls: type[Decimal128],
    _core_schema: CoreSchema,
    _handler: GetJsonSchemaHandler,
) -> dict[str, Any]:
    return {"bsonType": "decimal"}


def regex_json_schema(
    _cls: type[Regex[str]],
    _core_schema: CoreSchema,
    _handler: GetJsonSchemaHandler,
) -> dict[str, Any]:
    return {"bsonType": "regex"}


def date_schema(
    _cls: type[Timestamp],
    _core_schema: CoreSchema,
    _handler: GetJsonSchemaHandler,
) -> dict[str, Any]:
    return {"bsonType": "date"}
