# from __future__ import annotations

import inspect
import datetime
from enum import Enum
from uuid import UUID
from typing import (
    get_origin,
    Union,
    List,
    Any,
    dataclass_transform,
    Optional,
    Final,
    Literal,
    overload,
    Callable
)

from bson import Binary, ObjectId, Timestamp, Int64
from attrs import (
    field as _field,
    define,
    make_class,
    NOTHING
)

from .typings import xJsonT, Self, UnionType

InternalConverterT = Optional[Callable[[Any], Any]]

__all__ = [
    "SchemaGenerator",
    "field",
    "Document"
]

TYPE_MAP: dict[type, str] = {
    str: "string",
    bytes: "binData",
    float: "double",
    int: "int",
    list: "array",
    type(None): "null",
    ObjectId: "objectId",
    bool: "bool",
    datetime.datetime: "date",
    Binary: "binData",
    UUID: "binData",
    Timestamp: "timestamp",
    Int64: "long"
}

FIELD_NAME: Final[str] = "field_name"

_METADATA_KEYS: dict[str, str] = {
    "min": "minimum",
    "max": "maximum",
    "minlen": "minLength",
    "maxlen": "maxLength",
    "min_items": "minItems",
    "max_items": "maxItems",
    "unique_items": "uniqueItems"
}


def _collect_mro(cls: type, /, *, include_annotations: bool = False) -> xJsonT:
    """
    this collects all fields from class as _CountingAttr from attrs.
    works with subclasses.
    pass `include_annotations=True` to include annotations into return value
    """
    these: xJsonT = {}
    if not issubclass(cls, Document):
        raise Exception("is not a Document subclass")
    # respect subclasses order and exclude object and Document
    for x in cls.mro()[:-2][::-1]:
        for k, v in x.__annotations__.items():
            # fallback if its just annotation
            value = getattr(x, k, _field(type=v))
            # check for field
            if value.__class__.__name__ != "_CountingAttr":
                # if its just annotation with value
                value = _field(default=value, type=v)
            these[k] = value
        if include_annotations:
            these.setdefault("__annotations__", {}).update(x.__annotations__)
    return these


def _cls_to_baseclass_from_mro(cls: type, /) -> type:
    # needed for enums
    # <MyEnum foo: bar> will return <class 'Enum'>
    if hasattr(cls, "mro"):  # not all annotations have mro (e.g Literal)
        return cls.mro()[-2]  # at this position sits base class
    return cls


def _get_field_property(
    cls: type,
    field_name: str,
    property_name: str
) -> Any:
    _field_obj: Any = getattr(cls, field_name, None)
    cls_name: str = _field_obj.__class__.__name__

    # check if its actual field
    if _field_obj is not None and cls_name == "_CountingAttr":
        return getattr(_field_obj, property_name)  # raise error too


def _as_dict_helper(obj: "Document", /) -> xJsonT:
    """
    internal helper for `.to_dict()`
    """
    payload = {x: getattr(obj, x) for x in _get_parameter_names(obj)}
    for key, value in {**payload}.items():  # prevent dict keys change
        # handle subclasses correctly
        cls = _cls_to_baseclass_from_mro(value.__class__)
        metadata: xJsonT = _get_field_property(
            obj.__class__,
            key,
            "metadata"
        ) or {}

        # apply internal converter
        internal_converter: InternalConverterT = _CONVERTERS.get(
            cls, {}
        ).get("to")
        if internal_converter is not None:
            payload[key] = internal_converter(value)

        # apply field converter
        field_converter = _get_field_property(
            obj.__class__,
            key,
            "converter"
        )
        if field_converter is not None:
            payload[key] = field_converter(value)

        # replace keys according to metadata's `field_name` param
        if FIELD_NAME in metadata:
            payload[metadata[FIELD_NAME]] = payload.pop(key)
    return payload


def _get_parameter_names(obj: Any, /) -> list[str]:
    """
    return list of parameter names from `obj` `__init__` signature
    """
    return [*inspect.signature(obj.__init__).parameters.keys()]


class SchemaGenerator:
    def __init__(self, *, additional_properties: bool = False) -> None:
        self.additional_properties: bool = additional_properties

    def _get_field_name(self, name: str, cls: type, /) -> str:
        metadata: xJsonT = _get_field_property(cls, name, "metadata") or {}
        return metadata.get(FIELD_NAME, name)

    def _maybe_add_object_id_signature(self, payload: xJsonT, /) -> xJsonT:
        if self.additional_properties:
            return payload
        required: List[str] = payload["$jsonSchema"]["required"]
        required.append("_id")
        payload["$jsonSchema"]["properties"]["_id"] = {
            "bsonType": ["objectId"]
        }
        return payload

    def generate(self, cls: type, /, *, child: bool = False) -> xJsonT:
        if not issubclass(cls, Document):
            raise Exception("class must be inherited from Document")
        mro = _collect_mro(cls, include_annotations=True)
        annotations = mro.pop("__annotations__")
        required = [self._get_field_name(k, cls) for k in mro.keys()]
        payload: xJsonT = {
            "bsonType": ["object"],
            "required": required,  # make all fields required
            "properties": {},
            "additionalProperties": self.additional_properties,
        }
        for k in mro.keys():
            annotation = annotations[k]
            name = self._get_field_name(k, cls)
            payload["properties"][name] = {
                **self._get_type_data(annotation, attr_name=k),
                **self._generate_fixed_metadata(cls, k)
            }
        if not child:
            return self._maybe_add_object_id_signature({
                "$jsonSchema": {
                    **payload
                }
            })
        return payload

    def _get_type_data(
        self,
        attr_t: Any,
        attr_name: str,
        is_optional: bool = False
    ) -> xJsonT:
        if attr_t is None:
            return {"bsonType": ["null"]}
        origin = get_origin(attr_t)
        is_union: bool = origin in [UnionType, Union]
        if not is_union:
            if origin is Literal:  # like extended enum
                args = [
                    x.value if issubclass(type(x), Enum)
                    else x for x in attr_t.__args__
                ]
                dtypes = [self._lookup_type(type(val)) for val in args]
                return {
                    "enum": args + ([None] if is_optional else []),
                    "bsonType": list(set(dtypes))
                }
            elif origin is list:
                cls_: type = attr_t.__args__[0]
                return {
                    "bsonType": ["array"] + (["null"] if is_optional else []),
                    "items": {
                        **self._get_type_data(cls_, attr_name=attr_name)
                    }
                }
            if not isinstance(attr_t, type):
                _args = attr_t.__class__, attr_t
                raise Exception("Unsupported annotation found: %s, %s" % _args)

            if issubclass(attr_t, Enum):
                values = [z.value for z in attr_t]
                dtypes = [self._lookup_type(type(val)) for val in values]
                return {
                    "enum": values + ([None] if is_optional else []),
                    "bsonType": list(set(dtypes)) + (
                        ["null"] if is_optional else []
                    )
                }

            elif self._is_object(attr_t):
                return self.generate(attr_t, child=True)

            else:
                dtype = [self._lookup_type(attr_t)] + (
                    ["null"] if is_optional else []
                )
                return {"bsonType": dtype}
        else:
            args: List[type] = list(attr_t.__args__)
            is_optional = type(None) in args

            is_object: bool = any(self._is_object(cls) for cls in args)
            if is_object and len(args) != (1 + is_optional):
                exc_text = "Cannot specify other annotations with Document"
                raise Exception(exc_text)

            is_enum: bool = any(self._is_enum(cls) for cls in args)
            if is_enum and len(args) != (1 + is_optional):
                raise Exception("Cannot specify other annotations with Enum")

            payloads = [self._get_type_data(
                cls,
                attr_name=attr_name,
                is_optional=is_optional
            ) for cls in args]
            return self._merge_payloads(payloads)

    def _lookup_type(self, attr_t: Any, /) -> str:
        try:
            return TYPE_MAP[attr_t]
        except KeyError:
            raise Exception(f"Unsupported annotation: {attr_t}")

    def _is_object(self, attr_t: Any, /) -> bool:
        return isinstance(attr_t, type) and issubclass(attr_t, Document)

    def _is_enum(self, attr_t: Any, /) -> bool:
        return isinstance(attr_t, type) and issubclass(attr_t, Enum)

    def _merge_payloads(self, payloads: List[xJsonT], /) -> xJsonT:
        data: xJsonT = {"bsonType": []}
        for payload in payloads:
            data["bsonType"].extend(payload.pop("bsonType"))
            data.update(payload)
        data["bsonType"] = list(set(data["bsonType"]))
        return data

    def _generate_fixed_metadata(self, cls: type, attr_name: str) -> xJsonT:
        metadata: xJsonT = _get_field_property(
            cls,
            attr_name,
            "metadata"
        ) or {}
        unsupported: List[str] = [FIELD_NAME]
        return {
            _METADATA_KEYS.get(k, k): v
            for k, v in metadata.items()
            if k not in unsupported
        }


def filter_non_null(doc: xJsonT) -> xJsonT:
    return {k: v for k, v in doc.items() if v is not None}


# https://www.mongodb.com/docs/manual/reference/operator/query/jsonSchema/#available-keywords
# TODO: implement other?
def field(
    *,
    default: Any = NOTHING,
    converter: Any = None,
    title: Optional[str] = None,
    description: Optional[str] = None,
    min: Optional[int] = None,
    max: Optional[int] = None,
    min_items: Optional[int] = None,
    max_items: Optional[int] = None,
    minlen: Optional[int] = None,
    maxlen: Optional[int] = None,
    field_name: Optional[str] = None,
    pattern: Optional[str] = None,
    unique_items: bool = False,
    metadata: Optional[xJsonT] = None
) -> Any:
    metadata = metadata or {}
    not_needed: list[str] = ["metadata", "default", "not_needed", "converter"]
    payload = {
        **{k: v for k, v in locals().items() if k not in not_needed},
        **metadata
    }  # remove other
    if unique_items is False:
        del payload["unique_items"]
    metadata = filter_non_null(payload)
    return _field(default=default, metadata=metadata, converter=converter)


_cls_cache_map: dict[int, type] = {}


@dataclass_transform(field_specifiers=(field,))
class Document:
    """
    this is `magic` class that makes subclasses
    act like `attrs-defined` classes when initialization
    but not converting them to dataclasses instantly.
    `Document` is hooking child's `__new__` method
    changing its cls to `attrs-defined` one (cached).
    new instance has `__class__` attribute same as
    original one. (e.g for `isinstance()`)
    because subclassed classes are NOT being
    transformed into dataclasses instantly
    you cant use `fields()` or its friends from `attrs`.
    this library provides private api for that.
    i've decided to make its that way, because i didn't want
    to use `@define` and subclass from other class
    at the same time like
    >>>    @define # decorator
    >>>    class User(Document) # and Document
    >>>        ...

    Using decorator and subclass together looks ugly,
    so i've implemented this class.
    """
    _id: ObjectId

    def __new__(cls, *args: tuple[Any], **kwargs: xJsonT) -> Self:
        if id(cls) in _cls_cache_map:
            injected = _cls_cache_map[id(cls)]
        else:
            injected = make_class(
                cls.__name__,  # create a class with cls name
                _collect_mro(cls),  # attrs needed for class
                bases=(define(cls),),  # make cls be a dataclass
                class_body={"__class__": cls}  # trick for isinstance
            )
            _cls_cache_map[id(cls)] = injected
        obj = super().__new__(injected)
        obj.__init__(*args, **kwargs)
        return obj.id(ObjectId())

    def to_dict(self, *, exclude_id: bool = True) -> xJsonT:
        id_payload = {"_id": self._id} if not exclude_id else {}
        payload = _as_dict_helper(self)
        return {
            **payload,
            **id_payload
        }

    @classmethod
    def from_document(cls, document: xJsonT, /) -> Self:
        document = document.copy()
        mro = _collect_mro(cls, include_annotations=True)
        payload: xJsonT = {}
        annotations = mro.pop("__annotations__")
        for name, attr in mro.items():
            field_name = attr.metadata.get(FIELD_NAME, name)
            annotation = _cls_to_baseclass_from_mro(annotations[name])
            if annotation in _CONVERTERS:
                converter = _CONVERTERS[annotation]["from"]
                payload[name] = converter(
                    annotations[name], document[field_name]
                )
            else:
                payload[name] = document[field_name]  # TODO: fix dict ordering
        _id: ObjectId = document.get("_id", ObjectId())
        return cls(**payload).id(_id)

    @overload
    def id(self, _id: None = None, /) -> ObjectId:
        ...

    @overload
    def id(self, _id: ObjectId, /) -> Self:
        ...

    def id(self, _id: Optional[ObjectId] = None, /) -> Union[ObjectId, Self]:
        if _id is None:
            return self._id
        self._id = _id
        return self


_CONVERTERS: Final[dict[type, xJsonT]] = {
    UUID: {
        "to": lambda uuid: Binary.from_uuid(uuid),  # type: ignore
        "from": lambda _, value: value.as_uuid()  # type: ignore
    },
    Enum: {
        "to": lambda enm: enm.value,  # type: ignore
        "from": lambda cls, value: cls(value)  # type: ignore
    },
    Document: {
        "to": lambda doc: doc.to_dict(),  # type: ignore
        "from": lambda cls, value: cls.from_document(value)  # type: ignore
    }
}
