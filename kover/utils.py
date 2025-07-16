from __future__ import annotations

import itertools
from typing import (
    TYPE_CHECKING,
    Protocol,
    TypeVar,
    get_origin,
    runtime_checkable,
)

if TYPE_CHECKING:
    from collections.abc import Iterable

    from .typings import xJsonT

T = TypeVar("T")


@runtime_checkable
class HasToDict(Protocol):
    """Protocol for objects that can be converted to a dictionary."""

    def to_dict(self) -> xJsonT:  # noqa: D102
        ...


def chain(iterable: Iterable[Iterable[T]]) -> list[T]:
    """Flatten an iterable of iterables into a single list."""
    return [*itertools.chain.from_iterable(iterable)]


def filter_non_null(doc: xJsonT) -> xJsonT:
    """Filter out None values from a dictionary."""
    return {k: v for k, v in doc.items() if v is not None}


def isinstance_ex(attr_t: object, argument: type[object]) -> bool:
    """Check if `attr_t` is an instance of `argument` or a subclass thereof."""
    return isinstance(attr_t, type) and issubclass(attr_t, argument)


def is_origin_ex(attr_t: object, argument: object) -> bool:
    """Check if `attr_t` is an origin type of `argument`."""
    return get_origin(attr_t) is argument


def maybe_to_dict(obj: HasToDict | xJsonT | None) -> xJsonT | None:
    """Convert an object to a dictionary.

    Converts the object using its `to_dict` method if it has one,
    otherwise returns the object as is if it is already a dictionary or None.
    """
    if (obj is not None and isinstance(obj, dict)) or obj is None:
        return obj
    return obj.to_dict()
