from __future__ import annotations

from copy import deepcopy
from datetime import UTC, date, datetime
from decimal import Decimal
import re
from typing import Annotated, Any
from uuid import UUID, uuid4

from elune import (
    Binary,
    Code,
    DatetimeMS,
    DBRef,
    Decimal128,
    Int64,
    MaxKey,
    MinKey,
    ObjectId,
    Regex,
    Timestamp,
)
from pydantic import BaseModel, Field, IPvAnyAddress, TypeAdapter, create_model  # ruff: ignore[typing-only-third-party-import]
import pytest

from kover.exceptions import SchemaGenerationException
from kover.schema import Document, MongoDBSchemaGenerator
from kover.schema._pipeline import (  # ruff: ignore[import-private-name]
    map_types,
    mongodb_schema,
    normalize_schema,
    resolve_refs,
    validate_compatibility,
)


@pytest.mark.parametrize(
    ("annotation", "expected"),
    [
        (ObjectId, "objectId"),
        (Int64, "long"),
        (DatetimeMS, "date"),
        (Decimal128, "decimal"),
        (Binary, "binData"),
        (Timestamp, "timestamp"),
        (Regex, "regex"),
        (Code, ["javascript", "javascriptWithScope"]),
        (MinKey, "minKey"),
        (MaxKey, "maxKey"),
        (DBRef, "object"),
    ],
)
def test_native_bson_types(
    annotation: type,
    expected: str | list[str],
) -> None:
    model = create_model("Native", value=(annotation, ...), __base__=Document)
    ordinary = deepcopy(model.model_json_schema())

    core = repr(model.__pydantic_core_schema__)
    schema = model.model_mongodb_schema()
    result = schema["$jsonSchema"]["properties"]["value"]

    assert result["bsonType"] == expected
    assert model.model_json_schema() == ordinary
    assert repr(model.__pydantic_core_schema__) == core


def test_document_id_is_nullable_only_in_python() -> None:
    class Native(Document):
        value: ObjectId | None = None

    ordinary = deepcopy(Native.model_json_schema())
    core = repr(Native.__pydantic_core_schema__)
    schema = Native.model_mongodb_schema()["$jsonSchema"]
    assert schema["properties"]["_id"] == {"bsonType": "objectId"}
    assert schema["required"] == ["_id"]
    assert schema["properties"]["value"]["anyOf"] == [
        {"bsonType": "objectId"},
        {"bsonType": "null"},
    ]

    for document in (Native(), Native(_id=None)):
        assert document.object_id is None
        assert "_id" not in document.model_dump(by_alias=True)

    identifier = ObjectId()
    document = Native.model_validate({"_id": identifier})
    assert document.object_id == identifier
    assert document.model_dump(by_alias=True)["_id"] == identifier
    assert Native.model_json_schema() == ordinary
    assert repr(Native.__pydantic_core_schema__) == core


def test_native_bson_values_retain_native_serialization() -> None:
    class Native(Document):
        oid: ObjectId
        count: Int64
        price: Decimal128
        data: Binary

    model = Native.model_validate(
        {
            "oid": "507f1f77bcf86cd799439011",
            "count": 1,
            "price": "1.50",
            "data": b"hello",
        },
    )
    assert isinstance(model.model_dump()["oid"], ObjectId)
    assert isinstance(model.model_dump()["count"], Int64)
    assert isinstance(model.model_dump()["price"], Decimal128)
    assert isinstance(model.model_dump()["data"], Binary)
    assert model.model_dump(mode="json")["oid"] == str(model.oid)
    assert not hasattr(UUID, "__get_pydantic_core_schema__")
    identifier = uuid4()
    assert TypeAdapter(UUID).dump_python(identifier) is identifier


def test_bson_in_nested_containers_and_unions() -> None:
    class Native(Document):
        ids: list[ObjectId]
        mapping: dict[str, Timestamp]
        optional: Decimal128 | None = None
        pair: tuple[Binary, Int64]

    schema = Native.model_mongodb_schema()
    props = schema["$jsonSchema"]["properties"]
    assert props["ids"]["items"] == {"bsonType": "objectId"}
    assert props["mapping"]["additionalProperties"] == {
        "bsonType": "timestamp",
    }
    assert props["optional"]["anyOf"] == [
        {"bsonType": "decimal"},
        {"bsonType": "null"},
    ]
    assert props["pair"]["items"] == [
        {"bsonType": "binData"},
        {"bsonType": "long"},
    ]


def test_wire_shaped_string_is_not_an_object_id() -> None:
    class Native(Document):
        text: Annotated[str, Field(pattern="^[0-9a-fA-F]{24}$")]

    schema = Native.model_mongodb_schema()
    prop = schema["$jsonSchema"]["properties"]["text"]
    assert prop == {"bsonType": "string", "pattern": "^[0-9a-fA-F]{24}$"}


@pytest.mark.parametrize(
    "keyword",
    [
        "format",
        "transform",
        "examples",
        "contentEncoding",
        "contains",
        "propertyNames",
        "unevaluatedProperties",
        "discriminator",
        "$comment",
    ],
)
def test_unsupported_keywords_raise_with_path(keyword: str) -> None:
    class Unsupported(Document):
        value: str = Field(json_schema_extra={keyword: "unsupported"})

    with pytest.raises(
        SchemaGenerationException,
        match=re.escape(f"properties/value/{keyword}"),
    ):
        Unsupported.model_mongodb_schema()


def test_real_pydantic_format_is_rejected() -> None:
    class Unsupported(Document):
        address: IPvAnyAddress

    with pytest.raises(SchemaGenerationException, match="format"):
        Unsupported.model_mongodb_schema()


@pytest.mark.parametrize(
    "annotation",
    [
        Annotated[bytes, Field(min_length=1)],
        Annotated[Binary, Field(min_length=1)],
        Annotated[Code, Field(min_length=1)],
        Annotated[Decimal, Field(max_digits=5)],
        Annotated[Decimal, Field(decimal_places=2)],
        Annotated[datetime, Field(gt=datetime(2020, 1, 1, tzinfo=UTC))],
        date,
    ],
)
def test_unenforceable_native_constraints_raise(annotation: Any) -> None:  # ruff: ignore[any-type]
    model = create_model(
        "Unsupported",
        value=(annotation, ...),
        __base__=Document,
    )
    with pytest.raises(SchemaGenerationException):
        model.model_mongodb_schema()


def test_recursive_model_fails_explicitly() -> None:
    class Recursive(Document):
        child: Recursive | None = None

    with pytest.raises(SchemaGenerationException, match=r"recursive.*ref"):
        Recursive.model_mongodb_schema()


def test_shared_refs_are_independent_and_preserve_sibling_constraints() -> (
    None
):
    schema = {
        "type": "object",
        "$defs": {"Value": {"type": "integer", "minimum": 5}},
        "properties": {
            "a": {"$ref": "#/$defs/Value", "minimum": 1},
            "b": {"$ref": "#/$defs/Value"},
        },
    }
    original = deepcopy(schema)
    result = mongodb_schema(schema)["$jsonSchema"]["properties"]
    assert result["a"]["allOf"] == [
        {"bsonType": ["int", "long"], "minimum": 5},
        {"minimum": 1},
    ]
    result["a"]["allOf"][0]["minimum"] = 100
    assert result["b"]["minimum"] == 5
    assert schema == original


@pytest.mark.parametrize(
    "reference",
    ["https://example.com/schema", "#/$defs/Missing"],
)
def test_unresolvable_refs_raise(reference: str) -> None:
    with pytest.raises(SchemaGenerationException, match="ref"):
        resolve_refs({"$ref": reference})


@pytest.mark.parametrize(
    "stage",
    [
        resolve_refs,
        normalize_schema,
        map_types,
        validate_compatibility,
    ],
)
def test_pipeline_stages_make_independent_copies(stage: Any) -> None:  # ruff: ignore[any-type]
    source = {"properties": {"value": {"enum": [{"type": "data"}]}}}
    original = deepcopy(source)
    result = stage(source)
    result["properties"]["value"]["enum"][0]["type"] = "changed"
    assert source == original


@pytest.mark.parametrize(
    ("inclusive", "exclusive", "expected", "flag"),
    [
        (10, 5, 10, False),
        (5, 10, 10, True),
        (5, 5, 5, True),
    ],
)
def test_exclusive_minimum_keeps_stricter_bound(
    inclusive: int,
    exclusive: int,
    expected: int,
    *,
    flag: bool,
) -> None:
    result = normalize_schema(
        {"minimum": inclusive, "exclusiveMinimum": exclusive},
    )
    assert result == {"minimum": expected, "exclusiveMinimum": flag}


def test_tuple_with_tail_keeps_both_schemas() -> None:
    result = normalize_schema(
        {
            "type": "array",
            "prefixItems": [{"type": "string"}],
            "items": {"type": "integer"},
        },
    )
    assert result == {
        "type": "array",
        "items": [{"type": "string"}],
        "additionalItems": {"type": "integer"},
    }


def test_primitive_type_array_union() -> None:
    class Native(Document):
        value: int | str | None

    result = Native.model_json_schema(
        schema_generator=MongoDBSchemaGenerator,
        union_format="primitive_type_array",
    )
    assert result["$jsonSchema"]["properties"]["value"] == {
        "bsonType": ["int", "long", "string", "null"],
    }


def test_metadata_and_default_handling() -> None:
    class Native(Document):
        value: ObjectId | None = Field(
            None,
            title="Explicit",
            description="Description",
        )

    schema = Native.model_mongodb_schema()
    props = schema["$jsonSchema"]["properties"]
    assert props["value"]["title"] == "Explicit"
    assert props["value"]["description"] == "Description"
    assert "default" not in props["value"]
    assert "default" in Native.model_json_schema()["properties"]["value"]


def test_decimal_bounds_are_not_discarded() -> None:
    class Native(Document):
        amount: Annotated[Decimal, Field(gt=1, le=10, multiple_of=0.5)]

    schema = Native.model_mongodb_schema()
    prop = schema["$jsonSchema"]["properties"]["amount"]
    assert prop == {
        "bsonType": "decimal",
        "minimum": 1,
        "exclusiveMinimum": True,
        "maximum": 10,
        "multipleOf": 0.5,
    }


def test_explicit_root_id_is_not_overwritten() -> None:
    class Native(BaseModel):
        identifier: str = Field(alias="_id")

    result = Native.model_json_schema(schema_generator=MongoDBSchemaGenerator)
    assert result["$jsonSchema"]["properties"]["_id"] == {"bsonType": "string"}


@pytest.mark.parametrize(
    ("inclusive", "exclusive", "expected", "flag"),
    [(10, 5, 5, True), (5, 10, 5, False), (5, 5, 5, True)],
)
def test_exclusive_maximum_keeps_stricter_bound(
    inclusive: int,
    exclusive: int,
    expected: int,
    *,
    flag: bool,
) -> None:
    result = normalize_schema(
        {
            "maximum": inclusive,
            "exclusiveMaximum": exclusive,
        },
    )
    assert result == {"maximum": expected, "exclusiveMaximum": flag}
