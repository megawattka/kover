from enum import Enum


class ValidationLevel(Enum):
    STRICT = "STRICT"
    MODERATE = "MODERATE"


class IndexType(Enum):
    TEXT = "text"
    GEOSPATIAL = "geospatial"
    HASHED = "hashed"


class IndexDirection(Enum):
    ASCENDING = 1
    DESCENDING = -1
