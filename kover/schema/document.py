"""kover Document module."""

from __future__ import annotations

from typing import Any

from elune import ObjectId  # ruff: ignore[typing-only-third-party-import]
from pydantic import (
    BaseModel,
    ConfigDict,
    Field,
)
from pydantic.json_schema import SkipJsonSchema  # ruff: ignore[typing-only-third-party-import]

from kover.schema.generator import MongoDBSchemaGenerator


class Document(BaseModel):
    """Base class for any document.

    Use ``model_validate()`` to load MongoDB documents and ``model_dump()``
    to serialize with field aliases. The ``object_id`` field uses alias
    ``_id`` and is omitted from dumps while its value is None.
    """
    model_config = ConfigDict(
        extra="forbid",
        use_enum_values=True,
        serialize_by_alias=True,
    )

    # None means MongoDB has not assigned an ID yet, not a stored BSON null.
    object_id: ObjectId | SkipJsonSchema[None] = Field(
        default=None,
        alias="_id",
        exclude_if=lambda v: v is None,
    )

    @classmethod
    def model_mongodb_schema(cls) -> dict[str, Any]:
        """Generate the MongoDB JSON Schema validator for this document model.

        Unsupported constraints propagate ``SchemaGenerationException`` from
        the generator. Defaults remain Pydantic-only.

        Returns:
            A MongoDB validator document containing the generated schema
            under the ``"$jsonSchema"`` key.
        """
        return cls.model_json_schema(
            schema_generator=MongoDBSchemaGenerator,
        )
