"""Map MongoDB server replies to operation failures."""

from __future__ import annotations

from typing import TYPE_CHECKING

from ..error_codes import get_exception_type
from ..exceptions import OperationFailure

if TYPE_CHECKING:
    from ..typings import DictT


class ErrorMapper:
    """Convert MongoDB error replies into appropriate exceptions."""

    @staticmethod
    def _select_error(reply: DictT) -> DictT:
        """Select the most specific error document from a server reply.

        Returns:
            Selected error.
        """
        write_errors = reply.get("writeErrors")
        if write_errors:
            return write_errors[0]

        write_concern_error = reply.get("writeConcernError")
        if write_concern_error:
            return write_concern_error

        return reply

    @staticmethod
    async def _create_exception(error_reply: DictT) -> OperationFailure:
        """Create an exception from a selected MongoDB error document.

        Returns:
            Constructed exception.
        """
        code = error_reply.get("code")
        if code is None:
            return OperationFailure(-1, str(error_reply))

        exception_type = await get_exception_type(code=str(code))
        return exception_type(
            code,
            error_reply.get("errmsg", "Command failed"),
        )

    @staticmethod
    def _attach_metadata(
        error: OperationFailure,
        details: DictT,
        error_reply: DictT,
    ) -> OperationFailure:
        """Attach MongoDB metadata from both reply levels.

        Returns:
            Exception with attached metadata.
        """
        error.err_info = error_reply.get("errInfo")
        error.code_name = error_reply.get("codeName")
        error.details = details.copy()
        error.error_labels = (
            frozenset(details.get("errorLabels", []))
            | frozenset(error_reply.get("errorLabels", []))
        )
        return error

    async def get_exception(self, reply: DictT) -> OperationFailure:
        """Construct an exception based on a server reply.

        Returns:
            An instance of OperationFailure or a subclass thereof.
        """
        error_reply = self._select_error(reply)
        error = await self._create_exception(error_reply)
        return self._attach_metadata(error, reply, error_reply)

    async def check(self, reply: DictT) -> None:
        """Validate the command result."""
        if reply.get("ok") != 1:
            raise await self.get_exception(reply)

    async def check_writes(self, reply: DictT) -> None:
        """Validate write and write-concern failures."""
        if reply.get("writeErrors") or reply.get("writeConcernError"):
            raise await self.get_exception(reply)
