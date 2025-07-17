from __future__ import annotations

from typing import TYPE_CHECKING

from pydantic import BaseModel, ConfigDict
from pydantic.alias_generators import to_camel

if TYPE_CHECKING:
    from ..typings import xJsonT


class ReprMixin:
    def __repr__(self) -> str:
        return f"{self.__class__.__name__}()"

    def __str__(self) -> str:
        return self.__repr__()


class ModelMixin(BaseModel):
    """Base class for all models with camel case fields."""

    model_config = ConfigDict(
        alias_generator=to_camel,
        extra="ignore",
        arbitrary_types_allowed=True,
        use_enum_values=True,
    )

    def to_dict(self) -> xJsonT:
        """Convert the model to a dictionary with camel case keys."""
        return self.model_dump(by_alias=True, exclude_none=True)
