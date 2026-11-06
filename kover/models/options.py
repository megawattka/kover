"""Options source file."""

import math
from typing import Self

from pydantic import BaseModel, Field, model_validator

from .read_preference import ReadPreference


class DiscoveryOptions(BaseModel):
    """Initial selection settings; timeout values are seconds, not ms."""

    replica_set: str | None = None
    direct_connection: bool = False
    server_selection_timeout: float = 30.0
    connect_timeout: float | None = 10.0
    read_preference: ReadPreference = Field(default_factory=ReadPreference)
    local_threshold: float = 0.015

    @model_validator(mode="after")
    def _validate_options(self) -> Self:
        if self.local_threshold < 0 or math.isnan(self.local_threshold):
            raise ValueError("Invalid local threeshold")

        if (
            not math.isfinite(self.server_selection_timeout)
            or self.server_selection_timeout < 0
        ):
            raise ValueError(
                "server_selection_timeout must be finite and >= 0",
            )
        if self.connect_timeout is not None and (
            not math.isfinite(self.connect_timeout)
            or self.connect_timeout <= 0
        ):
            raise ValueError("connect_timeout must be finite and > 0, or None")

        if self.replica_set is not None and not self.replica_set:
            raise ValueError("replica_set must not be empty")

        return self
