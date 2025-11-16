"""Metadata definitions for Kover documents and fields."""

from __future__ import annotations

from dataclasses import asdict, dataclass, field
from typing import TYPE_CHECKING

from annotated_types import GroupedMetadata
from pydantic import Field
from pydantic.alias_generators import to_camel

from ..internals import EmptyReprMixin as _ReprMixin

if TYPE_CHECKING:
    from collections.abc import Iterator

    from ..typings import xJsonT


class ExcludeIfNone(_ReprMixin):
    """A metadata annotation for Document subclasses.

    Its excludes a field from the
    `.model_dump()` output if its value is `None`.

    Usage example:
        uid: Annotated[Optional[UUID], ExcludeIfNone()] = None

    This is useful for omitting optional fields from serialized representations
    when they are not set.
    """


@dataclass(frozen=True)
class SchemaMetadata(GroupedMetadata):
    """Specify additional jsonSchema metadata for MongoDB Schema generation.

    https://www.mongodb.com/docs/manual/reference/operator/query/jsonSchema/
    https://www.mongodb.com/docs/manual/reference/operator/query/jsonSchema/#available-keywords
    """

    title: str | None = field(default=None)
    description: str | None = field(default=None)
    minimum: int | None = field(default=None)
    maximum: int | None = field(default=None)
    min_items: int | None = field(default=None)
    max_items: int | None = field(default=None)
    min_length: int | None = field(default=None)
    max_length: int | None = field(default=None)
    pattern: str | None = field(default=None)
    unique_items: bool | None = field(default=None)

    def serialize(self) -> xJsonT:
        """Serialize the SchemaMetadata instance.

        Serializing to a dictionary with camelCase keys,
        omitting fields with None values.

        Returns:
            A dictionary representation of the SchemaMetadata instance.
        """
        serialized = asdict(self)
        for k in list(serialized.keys()):
            value = serialized.pop(k)
            if value is not None:
                serialized[to_camel(k)] = value
        return serialized

    def __iter__(self) -> Iterator[object]:
        """For GroupedMetadata. Raise validation Errors upon model creation."""
        yield Field(
            min_length=(self.min_items or self.min_length),
            max_length=(self.max_items or self.max_length),
            le=self.maximum,
            ge=self.minimum,
            title=self.title,
            description=self.description,
            pattern=self.pattern,
        )
