"""Enums and models used for collections."""

from enum import Enum


class ValidationLevel(Enum):
    """Validation levels for MongoDB collections."""

    STRICT = "STRICT"
    MODERATE = "MODERATE"
