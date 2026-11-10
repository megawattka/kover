"""MongoDB collation model."""

from enum import Enum
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field

from .._utils import ExcludeIfNone  # ruff: ignore[typing-only-first-party-import]


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

    model_config = ConfigDict(serialize_by_alias=True)

    locale: ExcludeIfNone[str] = None
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
        exclude_if=lambda v: v is None,
    )
    backwards: bool = False
    normalization: bool = False
