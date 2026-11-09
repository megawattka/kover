"""kover Document module."""

from __future__ import annotations

from typing import Any, Self

from bson import ObjectId  # ruff: ignore[typing-only-third-party-import]
from pydantic import (
    BaseModel,
    ConfigDict,
    PrivateAttr,
)

from .generator import MongoDBSchemaGenerator


class Document(BaseModel):
    """Base class for Kover documents.

    This class provides serialization, validation, and utility methods for
    working with MongoDB documents using Pydantic models.
    """
    model_config = ConfigDict(
        extra="forbid",
        use_enum_values=True,
    )
    _id: ObjectId | None = PrivateAttr(default=None)

    @classmethod
    def from_document(cls, payload: dict[str, Any]) -> Self:
        """Create a Document instance from a dictionary.

        Returns:
            An instance of the Document subclass with
                the data from the dictionary.
        """
        payload = dict(payload)
        object_id = payload.pop("_id", None)

        document = cls.model_validate(payload)
        if object_id is not None:
            document.set_object_id(object_id)

        return document

    def to_dict(self, *, exclude_id: bool = False) -> dict[str, Any]:
        """Convert the document to a dictionary.

        Returns:
            The document represented as a dictionary.
                If `exclude_id` is True, the `_id` field is excluded.
        """
        dumped = self.model_dump(by_alias=True)

        if not exclude_id and self._id is not None:
            return {"_id": self._id, **dumped}

        return dumped

    def set_object_id(self, _id: ObjectId) -> Self:
        """Set the document's ObjectId.

        Returns:
            self.
        """
        self._id = _id
        return self

    def get_object_id(self) -> ObjectId | None:
        """Get the document's ObjectId.

        Returns:
            The document's _id if set, otherwise None.
        """
        return self._id

    def __str__(self) -> str:
        return self.__repr__()

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
