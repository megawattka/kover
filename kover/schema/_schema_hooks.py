"""Pydantic integration for BSON value types.

Importing this module installs hooks that let Pydantic validate BSON values
and produce MongoDB-compatible JSON Schema for them.
"""

from __future__ import annotations

from typing import TYPE_CHECKING, Any
from uuid import UUID

from bson import (
    Binary,
    DatetimeMS,
    Decimal128,
    Int64,
    ObjectId,
    Regex,
    Timestamp,
)
from pydantic_core.core_schema import (
    is_instance_schema,
    no_info_after_validator_function,
    plain_serializer_function_ser_schema,
    union_schema,
)

from ._serializers import (
    bin_data_json_schema,
    date_schema,
    decimal_json_schema,
    long_json_schema,
    object_id_json_schema,
    regex_json_schema,
    validate_uuid,
)

if TYPE_CHECKING:
    from collections.abc import Callable

    from pydantic import GetCoreSchemaHandler
    from pydantic_core.core_schema import (
        CoreSchema,
    )


def _identity[T](value: T) -> T:
    """Return a validated value unchanged before serialization."""
    return value


def __pydantic_core_schema_gen__[T](  # ruff: ignore[dunder-function-name]
    cls: type[T],
    *,
    input_schema: CoreSchema | None = None,
    serializer: Callable[[T], Any] | None = None,
    validator: Callable[[Any], T] | None = None,
    return_schema: CoreSchema | None = None,
) -> classmethod[T, [Any, GetCoreSchemaHandler], CoreSchema]:
    def __get_pydantic_core_schema__(  # ruff: ignore[dunder-function-name]
        _cls: type[T],
        _source_type: object,
        _handler: GetCoreSchemaHandler,
    ) -> CoreSchema:
        source = input_schema or is_instance_schema(cls)

        if serializer is None and validator is None:
            return source

        serialization = None
        if serializer is not None:
            serialization = plain_serializer_function_ser_schema(
                serializer,
                return_schema=return_schema,
                when_used="always",
            )

        return no_info_after_validator_function(
            validator or _identity,
            source,
            serialization=serialization,
        )

    return classmethod(__get_pydantic_core_schema__)


def _install_hooks[T](
    cls: type[T],
    *,
    json_schema: Callable[..., Any],
    **schema_options: Any,  # ruff: ignore[any-type]
) -> None:
    """Install Pydantic hooks on a BSON class."""
    cls.__get_pydantic_core_schema__ = __pydantic_core_schema_gen__(  # pyright: ignore[reportAttributeAccessIssue]
        cls,
        **schema_options,
    )
    cls.__get_pydantic_json_schema__ = classmethod(json_schema)  # pyright: ignore[reportAttributeAccessIssue]


_install_hooks(Timestamp, json_schema=date_schema)
_install_hooks(Decimal128, json_schema=decimal_json_schema)
_install_hooks(Regex, json_schema=regex_json_schema)
_install_hooks(DatetimeMS, json_schema=date_schema)
_install_hooks(Binary, json_schema=bin_data_json_schema)
_install_hooks(Int64, json_schema=long_json_schema)
_install_hooks(ObjectId, json_schema=object_id_json_schema)

_install_hooks(
    UUID,
    input_schema=union_schema([
        is_instance_schema(UUID),
        is_instance_schema(Binary),
    ]),
    validator=validate_uuid,
    serializer=Binary.from_uuid,
    return_schema=is_instance_schema(Binary),
    json_schema=bin_data_json_schema,
)
