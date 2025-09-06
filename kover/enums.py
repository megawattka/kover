"""Enums, that are required for kover library."""

from enum import Enum


class ValidationLevel(Enum):
    """Validation levels for MongoDB collections."""

    STRICT = "STRICT"
    MODERATE = "MODERATE"


class IndexType(Enum):
    """Index types for MongoDB collections."""

    TEXT = "text"
    GEOSPATIAL = "geospatial"
    HASHED = "hashed"


class IndexDirection(Enum):
    """Index directions for MongoDB collections."""

    ASCENDING = 1
    DESCENDING = -1


class CollationStrength(Enum):
    """Collation strength levels for MongoDB collections."""

    PRIMARY = 1
    SECONDARY = 2
    TERTIARY = 3
    QUATERNARY = 4
    IDENTICAL = 5


class TxnState(Enum):
    """Transaction states for MongoDB transactions."""
    NONE = "NONE"
    STARTED = "STARTED"
    ABORTED = "ABORTED"
    COMMITED = "COMMITED"
