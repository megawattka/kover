"""Validated MongoDB hello response."""

from __future__ import annotations

from datetime import datetime  # ruff: ignore[typing-only-standard-library-import]
from typing import Any

from pydantic import BaseModel, ConfigDict, Field


class HelloResult(BaseModel):
    """Server capabilities and topology fields returned by ``hello``."""

    model_config = ConfigDict(extra="allow", populate_by_name=True)

    msg: str | None = None
    is_primary: bool = Field(default=False, alias="isWritablePrimary")
    is_replica_set: bool = Field(default=False, alias="isreplicaset")
    set_name: str | None = Field(default=None, alias="setName")
    secondary: bool = False
    arbiter_only: bool = Field(default=False, alias="arbiterOnly")
    hidden: bool = False
    tags: dict[str, str] = Field(default_factory=dict)
    last_write: dict[str, Any] = Field(default_factory=dict, alias="lastWrite")
    local_time: datetime | None = Field(default=None, alias="localTime")
    hosts: list[str] = Field(default_factory=list)
    passives: list[str] = Field(default_factory=list)
    arbiters: list[str] = Field(default_factory=list)
    me: str | None = None
    primary_node: str | None = Field(default=None, alias="primary")
    compression: list[str] = Field(default_factory=list)
    sasl_supported_mechs: list[str] = Field(
        default_factory=list,
        alias="saslSupportedMechs",
    )

    @property
    def requires_auth(self) -> bool:
        """Whether the server advertised authentication mechanisms."""
        return bool(self.sasl_supported_mechs)

    def get_auth_mechanism(self) -> str | None:
        """Choose the strongest supported SCRAM mechanism.

        Returns:
            The selected mechanism, or ``None`` when unsupported.
        """
        if "SCRAM-SHA-256" in self.sasl_supported_mechs:
            return "SCRAM-SHA-256"

        if "SCRAM-SHA-1" in self.sasl_supported_mechs:
            return "SCRAM-SHA-1"

        return None
