"""Pydantic documents and MongoDB schema generation."""

from .document import Document
from .generator import MongoDBSchemaGenerator

__all__ = (
    "Document",
    "MongoDBSchemaGenerator",
)
