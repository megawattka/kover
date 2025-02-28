from typing import Iterator, Optional
from dataclasses import dataclass, asdict

from pydantic import Field
from pydantic.alias_generators import to_camel
from annotated_types import GroupedMetadata


from ..typings import xJsonT


class _ReprMixin:
    def __repr__(self) -> str:
        return f"{self.__class__.__name__}()"

    def __str__(self) -> str:
        return self.__repr__()


class ExcludeIfNone(_ReprMixin):
    """
    Applicable only to Document subclasses
    Excludes Value from .model_dump() if the value is None
    e.g `uid: Annotated[Optional[UUID], ExcludeIfNone()] = None`
    """
    pass


@dataclass(frozen=True)
class SchemaMetadata(GroupedMetadata, _ReprMixin):
    """
    Specify additional jsonSchema metadata for MongoDB
    Schema generation
    https://www.mongodb.com/docs/manual/reference/operator/query/jsonSchema/
    https://www.mongodb.com/docs/manual/reference/operator/query/jsonSchema/#available-keywords
    """
    title: Optional[str] = None
    description: Optional[str] = None
    minimum: Optional[int] = None
    maximum: Optional[int] = None
    min_items: Optional[int] = None
    max_items: Optional[int] = None
    min_length: Optional[int] = None
    max_length: Optional[int] = None
    pattern: Optional[str] = None
    unique_items: Optional[bool] = None

    def serialize(self) -> xJsonT:
        serialized = asdict(self)
        for k in list(serialized.keys()):
            value = serialized.pop(k)
            if value is not None:
                serialized[to_camel(k)] = value
        return serialized

    def __iter__(self) -> Iterator[object]:
        """
        for GroupedMetadata. Raise valiadation Errors upon model creation
        """
        yield Field(
            min_length=(self.min_items or self.min_length),
            max_length=(self.max_items or self.max_length),
            le=self.maximum,
            ge=self.minimum,
            title=self.title,
            description=self.description,
            pattern=self.pattern
        )
