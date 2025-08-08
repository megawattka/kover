from __future__ import annotations

import itertools
from typing import (
    TYPE_CHECKING,
    TypeVar,
    get_origin,
)

if TYPE_CHECKING:
    from collections.abc import Callable, Iterable

    from .typings import HasToDict, xJsonT

T = TypeVar("T")


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
    if obj is None or isinstance(obj, dict):
        return obj
    return obj.to_dict()


def classrepr(*attributes: str) -> Callable[[type[T]], type[T]]:
    """Add a repr to class by decorator."""
    def inner(cls: type[T]) -> type[T]:
        def _gen_parts(obj: T) -> str:
            return ", ".join([f"{x}={getattr(obj, x)}" for x in attributes])

        def _cls_name(obj: T) -> str:
            return obj.__class__.__name__
        cls.__repr__ = lambda self: f"{_cls_name(self)}({_gen_parts(self)})"
        cls.__str__ = cls.__repr__
        return cls
    return inner
