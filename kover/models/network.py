"""Validated network configuration and pool resource snapshots."""

from typing import Self

from pydantic import ConfigDict, Field, model_validator

from ..enums import PoolState  # ruff: ignore[typing-only-first-party-import]
from ..mixins import ModelMixin


class _NetworkModel(ModelMixin):
    """Network data accepting Python field names and camel-case aliases."""

    model_config = ConfigDict(validate_by_name=True)


class PoolStats(_NetworkModel):
    """Snapshot of a pool's lifecycle state and resource counters."""

    state: PoolState
    idle: int = Field(ge=0)
    connecting: int = Field(ge=0)
    waiters: int = Field(ge=0)
    checked_out: int = Field(ge=0)


class Address(_NetworkModel):
    """MongoDB server hostname and TCP port."""

    host: str = Field(min_length=1)
    port: int = Field(default=27017, ge=1, le=65535)


class PoolOptions(_NetworkModel):
    """Connection pool limits with consistent minimum and maximum sizes."""

    max_size: int = Field(default=100, ge=1)
    min_size: int = Field(default=0, ge=0)
    max_connecting: int = Field(default=2, ge=1)
    max_idle_seconds: float | None = Field(default=None, ge=0)

    @model_validator(mode="after")
    def _validate_sizes(self) -> Self:
        if self.min_size > self.max_size:
            raise ValueError("min_size must not exceed max_size")
        return self


class DriverOptions(_NetworkModel):
    """Driver configuration excluding unsupported load-balanced mode."""

    pool: PoolOptions = Field(default_factory=PoolOptions)
    load_balanced: bool = False

    @model_validator(mode="after")
    def _validate_supported_features(self) -> Self:
        if self.load_balanced:
            raise ValueError("loadBalanced=true is not supported")
        return self
