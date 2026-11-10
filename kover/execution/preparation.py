"""Pure preparation of command and session metadata."""

from __future__ import annotations

from typing import TYPE_CHECKING

from ..policies.commands import is_read_command, supports_write_concern
from ..policies.routing import apply_rp_metadata, effective_read_preference
from .context import PreparedCommand

if TYPE_CHECKING:
    from ..models.address import Address
    from ..models.read_preference import ReadPreference
    from ..topology.protocols import IServerSelector
    from .context import OperationContext


def prepare_command(
    context: OperationContext,
    *,
    address: Address,
    selector: IServerSelector,
    default_preference: ReadPreference,
) -> PreparedCommand:
    """Add routing and session metadata without mutating the input.

    Returns:
        The prepared command and metadata.
    """
    command = context.command.copy()
    command.pop("$readPreference", None)
    is_read = is_read_command(command)
    preference, transactional = effective_read_preference(
        preference=context.read_preference or default_preference,
        is_read=is_read,
        session=context.session,
    )
    document, effective = apply_rp_metadata(
        command,
        address=address,
        selector=selector,
        preference=preference,
        is_read=is_read,
        transactional=transactional,
    )
    if (
        context.write_concern is not None
        and not transactional
        and supports_write_concern(document)
        and "writeConcern" not in document
    ):
        document["writeConcern"] = context.write_concern.model_dump()
    starts_transaction = False
    if context.session is not None:
        starts_transaction = context.session.apply_to(document)

    return PreparedCommand(
        document=document,
        address=address,
        is_read=is_read,
        transactional=transactional,
        preference=effective,
        starts_transaction=starts_transaction,
    )
