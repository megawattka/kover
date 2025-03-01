from __future__ import annotations

from enum import Enum
from types import UnionType
from typing import (
    Literal,
    Optional,
    Union,
    Any,
    Callable,
    Type,
    get_origin,
    List,
    TypeVar
)
from functools import partial
from typing_extensions import Self
from uuid import UUID
from bson import ObjectId, Binary
from pydantic import (
    BaseModel,
    ConfigDict,
    model_serializer,
    SerializationInfo,
    PrivateAttr
)
from pydantic.alias_generators import to_camel

from .metadata import ExcludeIfNone, SchemaMetadata
from .exceptions import SchemaGenerationException
from .typings import xJsonT
from ._internals import value_to_json_schema
from .utils import is_origin_ex, isinstance_ex


class SchemaGenerator:
    """
    this class is used for generating schemas for models
    that are subclassed from `kover.schema.Document`
    >>> generator = SchemaGenerator()
    >>> # assume we have model called "User"
    >>> schema = generator.generate(User)

    :param additional_properties: should be possible to add
        additional properties to documents? default False
        and not recommended to set to True.
    :param auto_append_long: by default if generator finds out
        that attrib has `int` annotation it also adds `long` to
        field signature. Same as python does for numbers.
        defaults to True.
        be aware that MongoDB can handle up to 8 bits only.
    """
    def __init__(
        self,
        *,
        additional_properties: bool = False,
        auto_append_long: bool = True
    ) -> None:
        self.additional_properties: bool = additional_properties
        self.auto_append_long = auto_append_long

    def _extract_args(self, attr_t: Any) -> List[Any]:
        if not hasattr(attr_t, "__args__"):
            raise SchemaGenerationException(
                f"Expecting type arguments for the generic class. {attr_t}"
            )
        return list(attr_t.__args__)

    def _generate_type_data(
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
            schema = value_to_json_schema(attr_t, is_optional=is_optional)
            if schema is not None:
                return schema
            elif origin is list:
                cls_: type = self._extract_args(attr_t)[0]
                return {
                    "bsonType": ["array"] + (["null"] if is_optional else []),
                    "items": {
                        **self._generate_type_data(cls_, attr_name=attr_name)
                    }
                }
            elif isinstance_ex(attr_t, Document):
                return self.generate(attr_t, child=True)  # type: ignore
            else:
                _args = attr_t.__class__, attr_t
                raise SchemaGenerationException(
                    "Unsupported annotation found: %s, %s" % _args
                )
        else:
            args: List[type] = self._extract_args(attr_t)
            is_optional = type(None) in args

            for func in [
                partial(isinstance_ex, argument=Document),
                partial(isinstance_ex, argument=Enum),
                partial(is_origin_ex, argument=Literal)
            ]:
                condition = any(func(cls) for cls in args)
                if condition and len(args) != (1 + is_optional):
                    kw = func.keywords["argument"]
                    raise SchemaGenerationException(
                        f"Cannot specify other annotations with {kw}"
                    )

            if sum([is_origin_ex(cls, list) for cls in args]) > 1:
                raise SchemaGenerationException(
                    "Multiple Lists are not allowed in Union"
                )

            payloads = [self._generate_type_data(
                cls,
                attr_name=attr_name,
                is_optional=is_optional
            ) for cls in args]
            return self._merge_payloads(payloads)

    def _merge_payloads(self, payloads: List[xJsonT], /) -> xJsonT:
        data: xJsonT = {"bsonType": []}

        for payload in payloads:
            data["bsonType"].extend(payload.pop("bsonType"))
            data.update(payload)

        data["bsonType"] = list(set(data["bsonType"]))
        if "enum" in data:
            data["enum"] = list(set(data["enum"]))

        return data

    def generate(
        self,
        cls: "Type[Document]",
        /,
        *,
        child: bool = False
    ) -> xJsonT:
        fields = cls.model_fields.items()
        required = [
            v.alias if v.alias else k
            for k, v in fields
        ]
        if "_id" in required:
            required.remove("_id")
        payload: xJsonT = {
            "bsonType": ["object"],
            "required": required,  # make all fields required
            "properties": {},
            "additionalProperties": self.additional_properties,
        }
        for k, v in fields:
            key = v.alias if v.alias else k
            payload["properties"][key] = {
                **self._generate_type_data(v.annotation, k),
                **self._generate_metadata(v.metadata)
            }
        if not child:
            return self._maybe_add_object_id_signature({
                "$jsonSchema": {
                    **payload
                }
            })
        return payload

    def _maybe_add_object_id_signature(self, payload: xJsonT, /) -> xJsonT:
        if self.additional_properties:
            return payload
        required: List[str] = payload["$jsonSchema"]["required"]
        required.append("_id")
        payload["$jsonSchema"]["properties"]["_id"] = {
            "bsonType": ["objectId"]
        }
        return payload

    def _generate_metadata(self, metadata: List[Any]) -> xJsonT:
        for _meta in metadata:
            if isinstance(_meta, SchemaMetadata):
                return _meta.serialize()
        return {}


class Document(BaseModel):
    model_config = ConfigDict(
        extra="allow",
        use_enum_values=True,
        arbitrary_types_allowed=True,
        alias_generator=to_camel,
        populate_by_name=True,
        validate_assignment=True
    )
    _id: Optional[ObjectId] = PrivateAttr(default=None)

    @model_serializer(mode="wrap")
    def serialize(
        self,
        wrap: Callable[[Self], dict[str, Any]],
        info: SerializationInfo
    ) -> dict[str, Any]:
        wrapped = wrap(self)
        for k, v in self.model_fields.items():
            if v.metadata and any(isinstance(x, ExcludeIfNone) for x in v.metadata):  # noqa: E501
                key = (v.alias if v.alias else k) if info.by_alias else k
                if getattr(self, k) is None:
                    wrapped.pop(key, None)
        if self.model_extra:
            for k in self.model_extra.keys():
                wrapped.pop(k, None)
        for k, v in wrapped.items():
            if isinstance(v, UUID):
                wrapped[k] = Binary.from_uuid(v)
        return wrapped

    @classmethod
    def from_document(cls, payload: xJsonT) -> Self:
        return cls.model_validate(payload)

    def model_post_init(self, ctx: Any) -> None:
        extra = (self.model_extra or {})
        _id: Optional[ObjectId] = extra.pop("_id", None)
        self._id = _id
        extra_keys = set(extra.keys())
        if extra_keys:
            raise ValueError(f"Unexpected fields: {extra_keys}")

    def to_dict(self, exclude_id: bool = False) -> xJsonT:
        dumped: xJsonT = self.model_dump(by_alias=True)
        if not exclude_id and self._id is not None:
            dumped = {"_id": self._id, **dumped}
        return dumped

    @classmethod
    def from_args(cls, *args: Any, **kwargs: Any) -> Self:
        """
        Initialize Document from non keyword arguments.
        (You cannot set _id that way)
        """
        properties = [
            v.alias if v.alias else k for k, v in cls.model_fields.items()
        ]
        keywords = {
            **dict(zip(properties, args)),
            **kwargs
        }
        return cls(**keywords)

    def with_id(self, _id: ObjectId) -> Self:
        self._id = _id
        return self

    def get_id(self) -> Optional[ObjectId]:
        return self._id

    def __eq__(self, other: Any) -> bool:
        if not isinstance(other, Document):
            raise NotImplementedError
        if self._id is not None and other._id is not None:
            return self._id == other._id
        return self.to_dict(exclude_id=True) == other.to_dict(exclude_id=True)

    def __str__(self) -> str:
        return self.__repr__()


T = TypeVar("T", bound=Document)


def model_configure(config: ConfigDict) -> Callable[[type[T]], Callable[..., T]]:  # noqa: E501
    """
    use this decorator on a class to change its model config.
    ```
    >>> class MyEnum(Enum):
    ...    FIRST = "1"
    ...    SECOND = "2"


    >>> @model_configure(ConfigDict(use_enum_values=False))  # True by default
    ... class Changed(Document):
    ...    test: MyEnum

    Changed(test=<MyEnum.FIRST: '1'>)
    ```
    """
    def outer(cls: type[T]) -> Callable[..., T]:
        cls.model_config.update(config)
        cls.model_rebuild(force=True)

        def inner(*args: Any, **kwargs: Any) -> T:
            return cls(*args, **kwargs)
        return inner
    return outer
