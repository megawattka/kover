"""Mapping helpers for kover."""

from __future__ import annotations

import itertools
from typing import TYPE_CHECKING, Any, overload

from ..__version__ import __version__
from ..configuration.environment import get_runtime_environment

if TYPE_CHECKING:
    from collections.abc import Iterable

    from .protocols import HasToDict


def get_hello_payload(
    compression: list[str] | None = None,
    application: dict[str, Any] | None = None,
) -> dict[str, Any]:
    """Build the initial hello command document.

    Returns:
        hello payload used for discovery and connecting.
    """
    payload: dict[str, Any] = {
        "hello": 1.0,
        "client": {
            "driver": {"name": "Kover", "version": __version__},
            **get_runtime_environment(),
        },
        "compression": compression or [],
    }
    if application is not None:
        payload["application"] = application
    return payload


def raw_decoder(payload: dict[str, Any]) -> dict[str, Any]:
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


def filter_non_null(doc: dict[str, Any]) -> dict[str, Any]:
    """Filter out None values from a dictionary.

    Returns:
        A new dictionary with all None values removed.
    """
    return {k: v for k, v in doc.items() if v is not None}


@overload
def maybe_to_dict(obj: HasToDict | dict[str, Any]) -> dict[str, Any]: ...


@overload
def maybe_to_dict(obj: None) -> None: ...


def maybe_to_dict(
    obj: HasToDict | dict[str, Any] | None,
) -> dict[str, Any] | None:
    """Convert an object to a dictionary.

    Converts the object using its `to_dict` method if it has one,
    otherwise returns the object as is if it is already a dictionary or None.

    Returns:
        The object converted to a dictionary, or None if the input is None.
    """
    if obj is None or isinstance(obj, dict):
        return obj
    return obj.to_dict()
