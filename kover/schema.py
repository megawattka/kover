from __future__ import annotations

import sys
import datetime
from typing import get_origin, Union, List, Any, Protocol

if sys.version_info < (3, 10):
    UnionType = Union
else:
    from types import UnionType
    
if sys.version_info < (3, 11):
    from typing_extensions import Self
else:
    from typing import Self

from attrs import define, field, fields, asdict, Attribute, has

from kover import xJsonT
from enum import Enum
from uuid import UUID
from bson import Binary, ObjectId, Timestamp

TYPE_MAP: dict[type, str] = {
    str: "string",
    float: "double",
    int: "int",
    list: "array",
    type(None): "null",
    ObjectId: "objectId",
    bool: "bool",
    datetime.datetime: "date",
    Binary: "binData",
    UUID: "binData",
    Timestamp: "timestamp"
}

FIELD_NAME = "fieldName"

class SchemaGenerator:
    def __init__(self, additional_properties: bool = False) -> None:
        self.additional_properties: bool = additional_properties

    def _get_field_name(self, attrib: Attribute) -> str:
        return attrib.metadata.get(FIELD_NAME, attrib.name)

    def generate(self, cls: type, child: bool = False) -> xJsonT:
        if not child and not issubclass(cls, Document):
            raise Exception("class must be inherited from Document")
        attribs: List[Attribute] = fields(cls)
        required = [self._get_field_name(attrib) for attrib in attribs if self._is_required(attrib)]
        payload: xJsonT = {
            "bsonType": ["object"],
            "required": required,
            "properties": {},
            "additionalProperties": self.additional_properties,
        }
        for attrib in attribs:
            assert attrib.type, "all fields must be annotated"
            name = self._get_field_name(attrib)
            payload["properties"][name] = {
                **self._get_type_data(attrib.type, attr_name=attrib.name),
                **self._generate_metadata(attrib)
            }
        if not child:
            return {
                "$jsonSchema": {
                    **payload
                }
            }
        return payload
    
    def _is_required(self, attrib: Attribute) -> bool:
        args = getattr(attrib.type, "__args__", [])
        return not (get_origin(attrib.type) in [UnionType, Union] and type(None) in args)
        
    def _get_type_data(self, attr_t: type, attr_name: str, is_optional: bool = False):
        is_union: bool = get_origin(attr_t) in [UnionType, Union]
        if not is_union:
            if get_origin(attr_t) is list:
                cls_: type = attr_t.__args__[0]
                return {
                    "bsonType": ["array"] + (["null"] if is_optional else []),
                    "items": {
                        **self._get_type_data(cls_, attr_name=attr_name)
                    }
                }
            elif issubclass(attr_t, Enum):
                values = [z.value for z in attr_t] + ([None] if is_optional else [])
                dtypes: List[Any] = [self._lookup_type(type(val)) for val in values] + (["null"] if is_optional else [])
                return {
                    "enum": values, 
                    "bsonType": list(set(dtypes))
                }
            
            elif self._is_define_decorated_class(attr_t):
                if issubclass(attr_t, Document):
                    raise Exception("Subdocuments cannot be subclassed from Document")
                return self.generate(attr_t, child=True)
            
            else:
                dtype = [self._lookup_type(attr_t)] + (["null"] if is_optional else [])
                return {"bsonType": dtype}
        else: 
            args: List[type] = list(attr_t.__args__)
            is_optional = type(None) in args

            is_object: bool = any(self._is_define_decorated_class(cls) for cls in args)
            if is_object and len(args) != (1 + is_optional):
                raise Exception("Cannot specify other annotations with define-decorated class")
            
            is_enum: bool = any(self._is_enum(cls) for cls in args)
            if is_enum and len(args) != (1 + is_optional):
                raise Exception("Cannot specify other annotations with Enum")

            payloads = [self._get_type_data(cls, attr_name=attr_name, is_optional=is_optional) for cls in args]
            return self._merge_payloads(payloads=payloads)

    def _lookup_type(self, attr_t: type) -> str:
        try:
            return TYPE_MAP[attr_t]
        except KeyError:
            raise Exception(f"Unsupported annotation: {attr_t}")
    
    def _is_define_decorated_class(self, attr_t: Any) -> bool:
        return has(attr_t)
    
    def _is_enum(self, attr_t: Any) -> bool:
        return isinstance(attr_t, type) and issubclass(attr_t, Enum)

    def _merge_payloads(self, payloads: List[xJsonT]) -> xJsonT:
        data = {"bsonType": []}
        for payload in payloads:
            data["bsonType"].extend(payload.pop("bsonType"))
            data.update(payload)
        data["bsonType"] = list(set(data["bsonType"]))
        return data

    def _generate_metadata(self, attrib: Attribute) -> xJsonT:
        if attrib.metadata is None:
            return {}
        metadata_keys: dict[str, str] = {
            "min": "minimum",
            "max": "maximum",
            "minlen": "minLength",
            "maxlen": "maxLength"
        } # TODO: add more options
        unsupported: List[str] = [FIELD_NAME]
        return {
            metadata_keys.get(k, k): v for k, v in attrib.metadata.items() if k not in unsupported
        }

class _DocumentLike(Protocol):
    _id: ObjectId

    def to_dict(self) -> xJsonT:
        raise NotImplemented

@define
class Document(_DocumentLike):
    _id: ObjectId = field(init=False, factory=ObjectId)

    def to_dict(self, exclude_id: bool = True) -> xJsonT:
        def value_serializer(_, __, value: Any):
            if isinstance(value, Enum):
                return value.value
            if isinstance(value, UUID): # UUID representation binary
                return Binary.from_uuid(value)
            return value
        payload = asdict(self, value_serializer=value_serializer)
        if exclude_id:
            del payload["_id"]
        for attrib in fields(self.__class__):
            if FIELD_NAME in attrib.metadata:
                payload[attrib.metadata[FIELD_NAME]] = payload.pop(attrib.name)
        return payload
    
    @classmethod
    def from_document(cls, document: xJsonT) -> Self:
        return cls(**document)