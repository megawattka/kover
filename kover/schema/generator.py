"""Pydantic entry point for MongoDB schema generation, without global hooks."""

from __future__ import annotations

from collections.abc import Callable
from functools import cached_property
from typing import TYPE_CHECKING, Any, cast, override

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
from pydantic import TypeAdapter
from pydantic.json_schema import GenerateJsonSchema

from kover.exceptions import SchemaGenerationException

from ._pipeline import mongodb_schema

if TYPE_CHECKING:
    from pydantic.annotated_handlers import CoreSchemaOrField
    from pydantic.json_schema import JsonSchemaMode
    from pydantic_core import CoreSchema
    from pydantic_core.core_schema import (
        BytesSchema,
        DateSchema,
        DatetimeSchema,
        DecimalSchema,
        UuidSchema,
    )


def _core_contract(value: Any) -> Any:  # ruff: ignore[any-type]
    """Compare native BSON core contracts, not ambiguous JSON wire shapes.

    Elune creates fresh Rust validator closures on every schema request.
    Their names and the surrounding core schemas are stable; their identities
    are not. Metadata and refs belong to the use site, not the type contract.

    Returns:
        A comparable structural fingerprint of a native core schema.
    """
    if isinstance(value, dict):
        return tuple(
            sorted(
                (key, _core_contract(child))
                for key, child in cast("dict[str, Any]", value).items()
                if key not in {"metadata", "ref"}
            ),
        )
    if isinstance(value, list):
        return tuple(
            _core_contract(child) for child in cast("list[Any]", value)
        )
    if isinstance(value, type):
        return value
    if isinstance(value, Callable):
        function = cast("Callable[..., Any]", value)
        return getattr(function, "__qualname__", repr(function))
    return value


class MongoDBSchemaGenerator(GenerateJsonSchema):
    """Generate strict MongoDB validators through copy-on-transform stages.

    Native BSON core schemas are adapted locally, leaving Elune's Pydantic
    validation and serialization untouched. References are expanded before
    normalization, type mapping and compatibility checking. Unsupported
    constraints raise ``SchemaGenerationException`` instead of disappearing.
    Only validation mode is supported. BSON binary subtypes and constraints
    inherent to BSON constructors are enforced by the application/codec.
    """

    @cached_property
    def _bson_contracts(self) -> list[tuple[Any, dict[str, Any]]]:
        return [
            (_core_contract(TypeAdapter(cls).core_schema), target)
            for cls, target in _BSON_SCHEMAS
        ]

    @override
    def generate(
        self,
        schema: CoreSchema,
        mode: JsonSchemaMode = "validation",
    ) -> dict[str, Any]:
        """Generate a collection validator.

        Returns:
            A MongoDB validator containing ``$jsonSchema``.

        Raises:
            ValueError: If serialization mode is requested.
        """
        if mode != "validation":
            raise ValueError("Only validation mode is supported.")

        return mongodb_schema(super().generate(schema, mode=mode))

    @override
    def generate_inner(self, schema: CoreSchemaOrField) -> dict[str, Any]:
        """Adapt native BSON contracts while retaining use-site metadata.

        Returns:
            A fresh schema for this core node.
        """
        if schema["type"] in {"json-or-python", "function-wrap"}:
            contract = _core_contract(schema)
            for native_contract, target in self._bson_contracts:
                if contract == native_contract:
                    metadata = schema.get("metadata", {})
                    return super().generate_inner(
                        {
                            "type": "any",
                            "metadata": {
                                **metadata,
                                "pydantic_js_updates": {
                                    **target,
                                    **metadata.get("pydantic_js_updates", {}),
                                },
                            },
                        },
                    )
        return super().generate_inner(schema)

    @override
    def field_title_should_be_set(self, schema: CoreSchemaOrField) -> bool:
        """Keep explicit titles, but do not synthesize field titles.

        Returns:
            False, disabling automatic field titles.
        """
        return False

    @override
    def bytes_schema(self, schema: BytesSchema) -> dict[str, Any]:
        """Represent bytes as BSON binary, rejecting unenforceable lengths.

        Returns:
            A BSON binary schema.
        """
        self._reject_constraints(schema, "min_length", "max_length")
        return {"bsonType": "binData"}

    @override
    def uuid_schema(self, schema: UuidSchema) -> dict[str, Any]:
        """Represent UUIDs as binary without changing UUID validation.

        Returns:
            A BSON binary schema.
        """
        self._reject_constraints(schema, "version")
        return {"bsonType": "binData"}

    @override
    def decimal_schema(self, schema: DecimalSchema) -> dict[str, Any]:
        """Retain numeric bounds, rejecting decimal digit/scale constraints.

        Returns:
            A decimal schema with all expressible numeric constraints.
        """
        self._reject_constraints(schema, "max_digits", "decimal_places")
        keys = {
            "ge": "minimum",
            "le": "maximum",
            "gt": "exclusiveMinimum",
            "lt": "exclusiveMaximum",
            "multiple_of": "multipleOf",
        }
        return {
            "bsonType": "decimal",
            **{
                target: schema[key]
                for key, target in keys.items()
                if key in schema
            },
        }

    @override
    def datetime_schema(self, schema: DatetimeSchema) -> dict[str, Any]:
        """Map datetime to BSON date without discarding constraints.

        Returns:
            A BSON date schema.
        """
        self._reject_constraints(
            schema,
            "ge",
            "le",
            "gt",
            "lt",
            "now_op",
            "tz_constraint",
        )
        return {"bsonType": "date"}

    @override
    def date_schema(self, schema: DateSchema) -> dict[str, Any]:
        """Reject dates, which BSON cannot encode without a conversion.

        Raises:
            SchemaGenerationException: Always; use datetime instead.
        """
        raise SchemaGenerationException(
            "datetime.date cannot be used as annotation; use datetime.",
        )

    @staticmethod
    def _reject_constraints(schema: Any, *keys: str) -> None:  # ruff: ignore[any-type]
        for key in keys:
            if key in schema:
                raise SchemaGenerationException(
                    f"MongoDB cannot enforce {key!r} for {schema['type']!r}.",
                )


_BSON_SCHEMAS: tuple[tuple[type, dict[str, Any]], ...] = (
    (ObjectId, {"bsonType": "objectId"}),
    (Int64, {"bsonType": "long"}),
    (DatetimeMS, {"bsonType": "date"}),
    (Decimal128, {"bsonType": "decimal"}),
    (Binary, {"bsonType": "binData"}),
    (Timestamp, {"bsonType": "timestamp"}),
    (Regex, {"bsonType": "regex"}),
    (Code, {"bsonType": ["javascript", "javascriptWithScope"]}),
    (MinKey, {"bsonType": "minKey"}),
    (MaxKey, {"bsonType": "maxKey"}),
    # DBRef is encoded as a document, not the deprecated BSON DBPointer.
    (
        DBRef,
        {
            "type": "object",
            "properties": {
                "$ref": {"type": "string"},
                "$id": {},
                "$db": {"type": "string"},
            },
            "required": ["$ref", "$id"],
        },
    ),
)
