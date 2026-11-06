"""Map MongoDB server replies to operation failures."""

from __future__ import annotations

from typing import Any

from ...error_codes import get_exception_type
from ...exceptions import OperationFailure


class ErrorMapper:
    """Convert MongoDB error replies into appropriate exceptions."""

    @staticmethod
    def _select_error(reply: dict[str, Any]) -> dict[str, Any]:
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
    async def _create_exception(
        error_reply: dict[str, Any],
    ) -> OperationFailure:
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
        details: dict[str, Any],
        error_reply: dict[str, Any],
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

    async def get_exception(self, reply: dict[str, Any]) -> OperationFailure:
        """Construct an exception based on a server reply.

        Returns:
            An instance of OperationFailure or a subclass thereof.
        """
        error_reply = self._select_error(reply)
        error = await self._create_exception(error_reply)
        return self._attach_metadata(error, reply, error_reply)

    async def check_reply(
        self,
        reply: dict[str, Any],
        *,
        with_writes: bool = False,
    ) -> None:
        """Validate the command result."""
        if reply.get("ok") != 1:
            raise await self.get_exception(reply)

        errors = reply.get("writeErrors") or reply.get("writeConcernError")
        if with_writes and errors:
            raise await self.get_exception(reply)
