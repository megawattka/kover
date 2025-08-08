from __future__ import annotations

import datetime
from enum import Enum
from typing import (
    TYPE_CHECKING,
    Any,
    Literal,
    get_origin,
)
from typing import is_typeddict as t_is_typeddict
from uuid import UUID

from typing_extensions import is_typeddict as te_is_typeddict

from ..bson import Binary, Int64, ObjectId, Timestamp
from ..exceptions import SchemaGenerationException, UnsupportedAnnotation
from ..helpers import chain

if TYPE_CHECKING:
    from types import UnionType

    from ..typings import xJsonT

_TYPE_MAP: dict[type, list[str]] = {
    str: ["string"],
    bytes: ["binData"],
    float: ["double"],
    int: ["int", "long"],
    list: ["array"],
    type(None): ["null"],
    ObjectId: ["objectId"],
    bool: ["bool"],
    datetime.datetime: ["date"],
    Binary: ["binData"],
    UUID: ["binData"],
    Timestamp: ["timestamp"],
    Int64: ["long"],
}


def _lookup_type(attr_t: type[object]) -> list[str]:
    try:
        return _TYPE_MAP[attr_t]
    except KeyError as e:
        raise UnsupportedAnnotation(attr_t) from e


def _serialize_literal(
    attr_t: UnionType,
    /,
    *,
    is_optional: bool = False,
) -> xJsonT:
    args = [
        x.value if issubclass(x.__class__, Enum)
        else x for x in attr_t.__args__
    ]
    dtypes = chain([_lookup_type(type(val)) for val in args])  # type: ignore
    return {
        "enum": args + ([None] if is_optional else []),
        "bsonType": sorted(set(dtypes)),
    }


def _is_typeddict_ex(attr_t: type[object]) -> bool:
    return t_is_typeddict(attr_t) or te_is_typeddict(attr_t)


# passing type data to dict unsupported and ignored
# use Document for that
# in that case it just creates AnyDict
# accepting any data passed to it. e.g custom metadata
# TODO @megawattka: TypedDict support
def _serialize_dict(
    attr_t: type[object],
    /,
    *,
    is_optional: bool = False,
) -> xJsonT:
    if not _is_typeddict_ex(attr_t):
        return {
            "bsonType": ["object"] + (["null"] if is_optional else []),
        }
    comment = "TypedDict currently not supported. Use Document."
    raise SchemaGenerationException(comment)


def _serialize_enum(
    attr_t: type[Enum],
    /,
    *,
    is_optional: bool = False,
) -> xJsonT:
    values = [z.value for z in attr_t]
    dtypes = chain([_lookup_type(type(val)) for val in values])  # type: ignore
    return {
        "enum": values + ([None] if is_optional else []),
        "bsonType": sorted(set(dtypes)) + (
            ["null"] if is_optional else []
        ),
    }


def _serialize_simple_type(
    attr_t: type[object],
    /,
    *,
    is_optional: bool = False,
) -> xJsonT:
    dtype = _lookup_type(attr_t) + (["null"] if is_optional else [])
    return {
        "bsonType": sorted(set(dtype)),
    }


def value_to_json_schema(
    attr_t: type[object],
    /,
    *,
    is_optional: bool = False,
) -> xJsonT | None:
    origin = get_origin(attr_t)
    if origin is None and _is_typeddict_ex(attr_t):
        origin = dict

    func = None
    origin_map: dict[Any, Any] = {
        Literal: _serialize_literal,
        dict: _serialize_dict,
    }
    if origin in origin_map:
        func = origin_map[origin]  # type: ignore

    elif isinstance(attr_t, type) and issubclass(attr_t, Enum):  # type: ignore
        func = _serialize_enum

    elif attr_t in _TYPE_MAP:
        func = _serialize_simple_type
    if func is not None:
        return func(attr_t, is_optional=is_optional)  # type: ignore

    return None  # ruff requires this to be explicit
