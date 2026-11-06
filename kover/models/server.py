"""Server models for kover module."""

from __future__ import annotations

from typing import TYPE_CHECKING, Any, Self

from pydantic import BaseModel, Field, model_validator

if TYPE_CHECKING:
    from pydantic import ModelWrapValidatorHandler


class BuildInfo(BaseModel):
    """Represents the result of a buildInfo command."""

    version: str
    git_version: str = Field(alias="gitVersion")
    allocator: str
    modules: list[str] = Field(default_factory=list)
    javascript_engine: str = Field(alias="javascriptEngine")
    version_array: list[int] = Field(alias="versionArray")
    openssl: str | None = Field(default=None)
    debug: bool
    bits: int
    max_bson_object_size: int = Field(alias="maxBsonObjectSize")
    storage_engines: list[str] = Field(alias="storageEngines")

    @model_validator(mode="wrap")
    @classmethod
    def _validate_openssl(
        cls,
        data: dict[str, Any],
        wrap: ModelWrapValidatorHandler[Self],
    ) -> Self:
        if "openssl" in data:
            data["openssl"] = data["openssl"]["running"]
        return wrap(data)

    def __str__(self) -> str:
        return self.__repr__()
