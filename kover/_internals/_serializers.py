import datetime
from uuid import UUID
from typing import (
    Literal,
    Any,
    Dict,
    get_origin,
    Optional
)
from enum import Enum
from types import UnionType

from bson import ObjectId, Binary, Timestamp, Int64

from ..utils import chain
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
    Int64: ["long"]
}


def _lookup_type(attr_t: Any, /) -> list[str]:
    # if attr_t is int and not append_long:
    #     return ["int"]
    try:
        return _TYPE_MAP[attr_t]
    except KeyError:
        raise Exception(
            f"Unsupported annotation: {attr_t}"
        )


def _serialize_literal(
    attr_t: UnionType,
    /,
    *,
    is_optional: bool = False
) -> xJsonT:
    args = [
        x.value if issubclass(x.__class__, Enum)
        else x for x in attr_t.__args__
    ]
    dtypes = chain([_lookup_type(type(val)) for val in args])
    return {
        "enum": args + ([None] if is_optional else []),
        "bsonType": sorted(set(dtypes))
    }


# passing type data to dict unsupported and ignored
# use Document for that
# in that case it just creates AnyDict
# accepting any data passed to it. e.g custom metadata
# TODO: probably add something here?
def _serialize_dict(attr_t: Any, /, *, is_optional: bool = False) -> xJsonT:
    return {
        "bsonType": ["object"] + (["null"] if is_optional else [])
    }


def _serialize_enum(
    attr_t: type[Enum],
    /,
    *,
    is_optional: bool = False
) -> xJsonT:
    values = [z.value for z in attr_t]
    dtypes = chain([_lookup_type(type(val)) for val in values])
    return {
        "enum": values + ([None] if is_optional else []),
        "bsonType": sorted(set(dtypes)) + (
            ["null"] if is_optional else []
        )
    }


def _serialize_simple_type(
    attr_t: Any,
    /,
    *,
    is_optional: bool = False
) -> xJsonT:
    dtype = _lookup_type(attr_t) + (["null"] if is_optional else [])
    return {
        "bsonType": sorted(set(dtype))
    }


def value_to_json_schema(
    attr_t: Any,
    /,
    *,
    is_optional: bool = False
) -> Optional[xJsonT]:
    origin = get_origin(attr_t)
    func = None
    _origin_map: Dict[Any, Any] = {
        Literal: _serialize_literal,
        dict: _serialize_dict
    }
    if origin in _origin_map:
        func = _origin_map[origin]  # type: ignore
    elif isinstance(attr_t, type) and issubclass(attr_t, Enum):
        func = _serialize_enum
    elif attr_t in _TYPE_MAP:
        func = _serialize_simple_type
    if func is not None:
        return func(attr_t, is_optional=is_optional)
