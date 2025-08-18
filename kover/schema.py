from __future__ import annotations

from enum import Enum
from types import UnionType
from typing import (
    TYPE_CHECKING,
    Any,
    Literal,
    ParamSpec,
    TypeVar,
    Union,
    get_origin,
)
from uuid import UUID

from pydantic import (
    BaseModel,
    ConfigDict,
    PrivateAttr,
    model_serializer,
)
from pydantic.alias_generators import to_camel
from typing_extensions import Self

from ._internals import value_to_json_schema
from .bson import Binary, ObjectId  # noqa: TC001
from .exceptions import SchemaGenerationException
from .helpers import classrepr, is_origin_ex, isinstance_ex
from .metadata import ExcludeIfNone, SchemaMetadata

if TYPE_CHECKING:
    from collections.abc import Callable

    from pydantic import SerializationInfo

    from .typings import xJsonT

P = ParamSpec("P")


@classrepr("additional_properties")
class SchemaGenerator:
    """Kover's Schema Generator.

    This class is used for generating schemas for models
    that are subclassed from `kover.schema.Document`.

    Examples:
        >>> generator = SchemaGenerator()
        >>> schema = generator.generate(User)  # our model

    Parameters:
        additional_properties : Should be possible to add
            additional properties to documents?
            Defaults to False and not recommended to set to True.
    """

    def __init__(
        self,
        *,
        additional_properties: bool = False,
    ) -> None:
        self.additional_properties: bool = additional_properties

    @staticmethod
    def _extract_args(attr_t: object) -> list[Any]:
        if not hasattr(attr_t, "__args__"):
            msg = f"Expecting type arguments for the generic class {attr_t}"
            raise SchemaGenerationException(msg)
        return list(getattr(attr_t, "__args__", []))

    def _generate_type_data(
        self,
        attr_t: type[object] | None,
        /,
        *,
        attr_name: str,
        is_optional: bool = False,
    ) -> xJsonT:
        if attr_t is None:
            return {"bsonType": ["null"]}
        origin = get_origin(attr_t)
        is_union: bool = origin in {UnionType, Union}

        if not is_union:
            schema = value_to_json_schema(attr_t, is_optional=is_optional)
            if schema is not None:
                return schema

            if origin is list:
                cls_: type = self._extract_args(attr_t)[0]
                return {
                    "bsonType": ["array"] + (["null"] if is_optional else []),
                    "items": {
                        **self._generate_type_data(cls_, attr_name=attr_name),
                    },
                }
            if isinstance_ex(attr_t, Document):
                return self.generate(attr_t, child=True)  # type: ignore

            # TODO @megawattka: deal with ForwardRef's
            args_ = attr_t.__class__, attr_t
            msg = "Unsupported annotation found: {}, {}".format(*args_)
            raise SchemaGenerationException(msg)

        args: list[type] = self._extract_args(attr_t)
        is_optional = type(None) in args

        for func, carg in [
            (isinstance_ex, Document),
            (isinstance_ex, Enum),
            (is_origin_ex, Literal),
        ]:
            condition = any(func(cls, carg) for cls in args)  # type: ignore
            if condition and len(args) != (1 + is_optional):
                raise SchemaGenerationException(
                    f"Cannot specify other annotations with {carg}")

        if sum(is_origin_ex(cls, list) for cls in args) > 1:
            raise SchemaGenerationException(
                "Multiple Lists are not allowed in Union")

        payloads = [self._generate_type_data(
            cls,
            attr_name=attr_name,
            is_optional=is_optional,
        ) for cls in args]

        return self._merge_payloads(payloads)

    @staticmethod
    def _merge_payloads(payloads: list[xJsonT], /) -> xJsonT:
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
        cls: type[Document],
        /,
        *,
        child: bool = False,
    ) -> xJsonT:
        """Generate a JSON schema for the given Document subclass.

        Parameters:
            cls : The Document subclass to generate the schema for.
            child : If True, generates schema for
                nested documents (default is False).

        Returns:
            The generated JSON schema as a dictionary.
        """
        fields = cls.model_fields.items()
        required = [
            v.alias or k
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
            key = v.alias or k
            payload["properties"][key] = {
                **self._generate_type_data(v.annotation, attr_name=k),
                **self._generate_metadata(v.metadata),
            }
        if not child:
            return self._maybe_add_object_id_signature({
                "$jsonSchema": {**payload},
            })
        return payload

    def _maybe_add_object_id_signature(self, payload: xJsonT, /) -> xJsonT:
        if self.additional_properties:
            return payload

        required: list[str] = payload["$jsonSchema"]["required"]
        if "_id" not in required:
            required.append("_id")

        payload["$jsonSchema"]["properties"]["_id"] = {
            "bsonType": ["objectId"],
        }
        return payload

    @staticmethod
    def _generate_metadata(metadata: list[Any]) -> xJsonT:
        for _meta in metadata:
            if isinstance(_meta, SchemaMetadata):
                return _meta.serialize()
        return {}


class Document(BaseModel):
    """Base class for Kover documents.

    This class provides serialization, validation, and utility methods for
    working with MongoDB documents using Pydantic models.
    """
    model_config = ConfigDict(
        extra="allow",
        use_enum_values=True,
        arbitrary_types_allowed=True,
        alias_generator=to_camel,  # uses alias generator, be careful!
        populate_by_name=True,
        validate_assignment=True,
    )
    _id: ObjectId | None = PrivateAttr(default=None)

    @model_serializer(mode="wrap")
    def _serialize(
        self,
        wrap: Callable[[Self], dict[str, Any]],
        info: SerializationInfo,
    ) -> dict[str, Any]:
        wrapped = wrap(self)
        for k, v in self.__pydantic_fields__.items():
            if v.metadata and any(isinstance(x, ExcludeIfNone) for x in v.metadata):  # noqa: E501
                key = (v.alias or k) if info.by_alias else k
                if getattr(self, k) is None:
                    wrapped.pop(key, None)

        if self.model_extra:
            for k in self.model_extra:
                wrapped.pop(k, None)

        for k, v in wrapped.items():
            if isinstance(v, UUID):
                wrapped[k] = Binary.from_uuid(v)

        return wrapped

    @classmethod
    def from_document(cls, payload: xJsonT) -> Self:
        """Create a Document instance from a dictionary."""
        return cls.model_validate(payload)

    def to_dict(self, *, exclude_id: bool = False) -> xJsonT:
        """Convert the document to a dictionary."""
        dumped: xJsonT = self.model_dump(by_alias=True)
        if not exclude_id and self._id is not None:
            dumped = {"_id": self._id, **dumped}
        return dumped

    def model_post_init(self, _ctx: object) -> None:
        """Document's post init function. Do NOT subclass."""
        extra = (self.model_extra or {})
        document_id: ObjectId | None = extra.pop("_id", None)
        self._id = document_id

    def __eq__(self, other: object) -> bool:
        if not isinstance(other, Document):
            raise NotImplementedError

        if self._id is not None and other._id is not None:
            return self._id == other._id

        return self.to_dict(exclude_id=True) == other.to_dict(exclude_id=True)

    def __hash__(self) -> int:
        """Hash based on id if present, otherwise error."""
        if self._id is not None:
            return hash(self._id)
        raise NotImplementedError("Hash requires _id set.")

    def with_id(self, _id: ObjectId) -> Self:
        """Set the document's ObjectId."""
        self._id = _id
        return self

    def get_id(self) -> ObjectId | None:
        """Get the document's ObjectId."""
        return self._id

    def __str__(self) -> str:
        return self.__repr__()


T = TypeVar("T", bound=Document)


def model_configure(config: ConfigDict) -> Callable[[type[T]], Callable[P, T]]:
    """Use this decorator on a class to change its model config.

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
    def outer(cls: type[T]) -> Callable[P, T]:
        cls.model_config.update(config)
        cls.model_rebuild(force=True)

        def inner(*args: P.args, **kwargs: P.kwargs) -> T:
            return cls(*args, **kwargs)
        return inner
    return outer
