"""Options source file."""

import math
from typing import Literal, Self

from pydantic import BaseModel, Field, model_validator

from ..models.read_preference import ReadPreference

MIN_HEARTBEAT_INTERVAL = 0.5
type MonitoringMode = Literal["auto", "poll", "stream"]


class DiscoveryOptions(BaseModel):
    """Initial selection settings; timeout values are seconds, not ms."""

    replica_set: str | None = None
    direct_connection: bool = False
    server_selection_timeout: float = 30.0
    connect_timeout: float | None = 10.0
    read_preference: ReadPreference = Field(default_factory=ReadPreference)
    local_threshold: float = 0.015
    heartbeat_frequency: float = Field(
        default=10.0,
        ge=MIN_HEARTBEAT_INTERVAL,
        allow_inf_nan=False,
    )
    server_monitoring_mode: MonitoringMode = "auto"

    @model_validator(mode="after")
    def _validate_options(self) -> Self:
        if self.local_threshold < 0 or math.isnan(self.local_threshold):
            msg = "Invalid local threeshold"
            raise ValueError(msg)

        if (
            not math.isfinite(self.server_selection_timeout)
            or self.server_selection_timeout < 0
        ):
            msg = "server_selection_timeout must be finite and >= 0"
            raise ValueError(
                msg,
            )
        if self.connect_timeout is not None and (
            not math.isfinite(self.connect_timeout)
            or self.connect_timeout <= 0
        ):
            msg = "connect_timeout must be finite and > 0, or None"
            raise ValueError(msg)

        if self.replica_set is not None and not self.replica_set:
            msg = "replica_set must not be empty"
            raise ValueError(msg)

        return self
