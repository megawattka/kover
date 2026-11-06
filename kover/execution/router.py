"""Address resolution for command execution."""

from __future__ import annotations

from typing import TYPE_CHECKING, Any

from ..policies.commands import is_read_command
from ..policies.routing import effective_read_preference, resolve_address

if TYPE_CHECKING:
    from ..models.address import Address
    from ..models.read_preference import ReadPreference
    from ..session import Session
    from ..topology.protocols import IServerSelector


async def route_command(
    command: dict[str, Any],
    *,
    selector: IServerSelector,
    default_preference: ReadPreference,
    session: Session | None,
    cursor_address: Address | None,
    read_preference: ReadPreference | None,
    deadline: float | None,
) -> Address:
    """Resolve cursor affinity, transaction pinning, or normal selection.

    Returns:
        The selected server address.
    """
    preference, _ = effective_read_preference(
        preference=read_preference or default_preference,
        is_read=is_read_command(command),
        session=session,
    )
    return await resolve_address(
        command,
        selector=selector,
        preference=preference,
        session=session,
        cursor_address=cursor_address,
        deadline=deadline,
    )
