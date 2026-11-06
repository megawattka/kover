"""Representation utilities for kover."""

from __future__ import annotations

from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from collections.abc import Callable


def classrepr[T](*attributes: str) -> Callable[[type[T]], type[T]]:
    """Add a repr to class by decorator.

    Returns:
        A decorator that adds a `__repr__` method to the class,
        which includes the specified attributes in the representation.
    """
    def inner(cls: type[T]) -> type[T]:
        def _gen_parts(obj: T) -> str:
            return ", ".join([f"{x}={getattr(obj, x)}" for x in attributes])

        def _cls_name(obj: T) -> str:
            return obj.__class__.__name__

        cls.__repr__ = lambda self: f"{_cls_name(self)}({_gen_parts(self)})"
        cls.__str__ = cls.__repr__
        return cls
    return inner
