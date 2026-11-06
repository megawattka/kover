"""Data passed between command-execution stages."""

from __future__ import annotations

from typing import Any

from pydantic import BaseModel, ConfigDict

from ..models.address import Address  # ruff: ignore[typing-only-first-party-import]
from ..models.concerns import WriteConcern  # ruff: ignore[typing-only-first-party-import]
from ..models.read_preference import ReadPreference  # ruff: ignore[typing-only-first-party-import]
from ..session import Session  # ruff: ignore[typing-only-first-party-import]


class OperationContext(BaseModel):
    """All inputs needed to route and prepare one command."""

    model_config = ConfigDict(arbitrary_types_allowed=True)

    command: dict[str, Any]
    database: str = "admin"
    session: Session | None = None
    read_preference: ReadPreference | None = None
    server_address: Address | None = None
    deadline: float | None = None
    write_concern: WriteConcern | None = None


class PreparedCommand(BaseModel):
    """Command document and routing metadata produced before I/O."""

    document: dict[str, Any]
    address: Address
    preference: ReadPreference
    is_read: bool
    transactional: bool
    starts_transaction: bool = False


class ExecutionResult(BaseModel):
    """Reply and address used for a command execution."""

    reply: dict[str, Any]
    address: Address


class CommandReply(dict[str, Any]):  # ruff: ignore[subclass-builtin]
    """Command response retaining its server address for cursor affinity."""

    def __init__(self, reply: dict[str, Any], address: Address) -> None:
        super().__init__(reply)
        self.server_address = address
