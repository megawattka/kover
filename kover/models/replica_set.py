"""Models for MongoDB replica set configurations."""

from __future__ import annotations

from typing import Any

from elune import ObjectId  # ruff: ignore[typing-only-third-party-import]
from pydantic import BaseModel, ConfigDict, Field


# https://www.mongodb.com/docs/manual/reference/replica-configuration/#members
class ReplicaSetMember(BaseModel):
    """Represents a MongoDB replica set member document."""

    member_id: int = Field(serialization_alias="_id", alias="member_id")
    host: str
    arbiter_only: bool = Field(default=False)
    build_indexes: bool = Field(default=True)
    hidden: bool = Field(default=False)
    priority: int = Field(default=1)
    tags: dict[str, Any] | None = Field(default=None)
    secondary_delay_secs: int = Field(default=0)
    votes: int = Field(default=1)


# https://www.mongodb.com/docs/manual/reference/replica-configuration/#settings
class ReplicaSetConfigSettings(BaseModel):
    """Represents a MongoDB replica set settings document."""

    model_config = ConfigDict(arbitrary_types_allowed=True)

    replica_set_id: ObjectId
    chaining_allowed: bool = Field(default=True)
    get_last_error_modes: dict[str, Any] | None = Field(default=None)
    heartbeat_timeout_secs: int = Field(default=10)
    election_timeout_millis: int = Field(default=10000)
    catch_up_timeout_millis: int = Field(default=-1)
    catch_up_takeover_delay_millis: int = Field(default=-1)


# https://www.mongodb.com/docs/manual/reference/replica-configuration/#replica-set-configuration-document-example
class ReplicaSetConfig(BaseModel):
    """Represents a MongoDB replica set configuration document."""

    rs_name: str = Field(serialization_alias="_id", alias="rs_name")
    version: int
    term: int
    members: list[ReplicaSetMember]
    configsvr: bool = Field(default=False)
    protocol_version: int = Field(
        default=1,
        serialization_alias="protocolVersion",
    )
    write_concern_majority_journal_default: bool = Field(
        default=True,
        serialization_alias="writeConcernMajorityJournalDefault",
    )
    settings: ReplicaSetConfigSettings | None = None

    @classmethod
    def default(cls) -> ReplicaSetConfig:
        """Create a default replica set configuration.

        Returns:
            The instance of default ReplicaSetConfig.
        """
        return cls(
            rs_name="rs0",
            version=1,
            term=0,
            members=[ReplicaSetMember(member_id=0, host="127.0.0.1:27017")],
        )

    def to_dict(self) -> dict[str, Any]:
        """Serialize model into dict.

        Returns:
            Serialized payload.
        """
        return self.model_dump()
