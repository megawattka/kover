"""MongoDB collation model."""

from enum import Enum
from typing import Any, Literal

from pydantic import BaseModel, Field


class CollationStrength(Enum):
    """Collation strength levels for MongoDB collections."""

    PRIMARY = 1
    SECONDARY = 2
    TERTIARY = 3
    QUATERNARY = 4
    IDENTICAL = 5


# https://www.mongodb.com/docs/manual/reference/collation/
class Collation(BaseModel):
    """Represents a MongoDB collation document."""

    locale: str | None = None
    case_level: bool = Field(default=False, serialization_alias="caseLevel")
    case_first: Literal["lower", "upper", "off"] = Field(
        default="off",
        serialization_alias="caseFirst",
    )
    strength: CollationStrength = CollationStrength.TERTIARY
    numeric_ordering: bool = Field(
        default=False,
        serialization_alias="numericOrdering",
    )
    alternate: Literal["non-ignorable", "shifted"] = "non-ignorable"
    max_variable: Literal["punct", "space"] | None = Field(
        default=None,
        serialization_alias="maxVariable",
    )
    backwards: bool = False
    normalization: bool = False

    def to_dict(self) -> dict[str, Any]:
        """Return the model as a dictionary using serialization aliases."""
        return self.model_dump(by_alias=True, exclude_none=True)
