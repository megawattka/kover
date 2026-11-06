"""Pure command routing rules."""

from __future__ import annotations

from typing import TYPE_CHECKING, Any

from ..models.read_preference import ReadPreference
from ..models.topology import ServerType
from ..models.tx_state import TxnState

if TYPE_CHECKING:
    from ..models.address import Address
    from ..session import Session
    from ..topology.protocols import IServerSelector


def effective_read_preference(
    preference: ReadPreference,
    *,
    is_read: bool,
    session: Session | None,
) -> tuple[ReadPreference, bool]:
    """Resolve transaction restrictions and read preference applicability.

    Returns:
        The effective preference and whether the session is transactional.

    Raises:
        ValueError: If a transaction requests a non-primary read preference.
    """
    transactional = session is not None and (
        session.in_transaction or session.state is TxnState.COMMITTING
    )
    if transactional and is_read and preference.mode != "primary":
        raise ValueError("transaction reads require readPreference=primary")
    return (
        preference if is_read and not transactional else ReadPreference(),
        transactional,
    )


def apply_rp_metadata(
    command: dict[str, Any],
    *,
    address: Address,
    selector: IServerSelector,
    preference: ReadPreference,
    is_read: bool,
    transactional: bool,
) -> tuple[dict[str, Any], ReadPreference]:
    """Prepare command read-preference metadata for the selected server.

    Returns:
        A copied command and the preference used to prepare it.
    """
    result = command.copy()
    result.pop("$readPreference", None)
    if not is_read or transactional:
        return result, preference

    role = selector.description(address).server_type
    if role is ServerType.STANDALONE:
        return result, preference

    effective = preference
    if (
        selector.direct_connection
        and role is not ServerType.MONGOS
        and effective.mode == "primary"
    ):
        effective = ReadPreference(mode="primaryPreferred")

    if effective.mode != "primary":
        result["$readPreference"] = effective.to_dict()
    return result, effective


async def resolve_address(
    command: dict[str, Any],
    *,
    selector: IServerSelector,
    preference: ReadPreference,
    session: Session | None,
    cursor_address: Address | None,
    deadline: float | None,
) -> Address:
    """Resolve cursor affinity, transaction pinning, or normal selection.

    Returns:
        The address that must execute the command.

    Raises:
        ValueError: If a cursor command has no server affinity address.
    """
    name = next(iter(command), "")
    if name in {"getMore", "killCursors"}:
        if cursor_address is None:
            raise ValueError(f"{name} requires the cursor's server address")
        return cursor_address

    if session is not None and (
        session.in_transaction or session.state is TxnState.COMMITTING
    ):
        pinned = session.pinned_server_address
        if pinned is not None:
            return pinned

    return await selector.select(preference, deadline=deadline)
