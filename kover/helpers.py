"""kover's helpers and utilities."""

from __future__ import annotations

import itertools
import os
import platform
import sys
from typing import (
    TYPE_CHECKING,
    overload,
)

from . import __version__

if TYPE_CHECKING:
    from collections.abc import Callable, Iterable

    from .typings import HasToDict, DictT


def resolve_auth_db_from_env(
    key: str = "MONGO_AUTH_DB",
    default: str = "admin",
) -> str:
    """Fn to get auth db from env.

    Returns:
        db name used for authentication.
    """
    return os.getenv(key, default)


def get_hello_payload(
    compression: list[str] | None = None,
    application: DictT | None = None,
) -> DictT:
    """Build the initial hello command document.

    Returns:
        hello payload used for discovery and connecting.
    """
    uname = platform.uname()
    implementation = sys.implementation
    version = ".".join(map(str, implementation.version))
    payload: DictT = {
        "hello": 1.0,
        "client": {
            "driver": {"name": "Kover", "version": __version__},
            "os": {
                "type": os.name,
                "name": uname.system,
                "architecture": uname.machine,
                "version": uname.release,
            },
            "platform": implementation.name + " " + version,
        },
        "compression": compression or [],
    }
    if application is not None:
        payload["application"] = application
    return payload


def raw_decoder(payload: DictT) -> DictT:
    """Return the payload unchanged.

    Args:
        payload: JSON-compatible payload to decode.

    Returns:
        The original payload without any modifications.
    """
    return payload


def chain[T](iterable: Iterable[Iterable[T]]) -> list[T]:
    """Flatten an iterable of iterables into a single list.

    Returns:
        Flattened list containing all elements from the input iterables.
    """
    return [*itertools.chain.from_iterable(iterable)]


def filter_non_null(doc: DictT) -> DictT:
    """Filter out None values from a dictionary.

    Returns:
        A new dictionary with all None values removed.
    """
    return {k: v for k, v in doc.items() if v is not None}


@overload
def maybe_to_dict(obj: HasToDict | DictT) -> DictT:
    ...


@overload
def maybe_to_dict(obj: None) -> None:
    ...


def maybe_to_dict(obj: HasToDict | DictT | None) -> DictT | None:
    """Convert an object to a dictionary.

    Converts the object using its `to_dict` method if it has one,
    otherwise returns the object as is if it is already a dictionary or None.

    Returns:
        The object converted to a dictionary, or None if the input is None.
    """
    if obj is None or isinstance(obj, dict):
        return obj
    return obj.to_dict()


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
