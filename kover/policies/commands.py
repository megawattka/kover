"""Pure command classification helpers."""

from __future__ import annotations

from typing import Any, Final

_READ_COMMANDS: Final[frozenset[str]] = frozenset(
    {"find", "count", "distinct", "aggregate"},
)
_CURSOR_COMMANDS: Final[frozenset[str]] = frozenset(
    {"getMore", "killCursors"},
)
_WRITE_CONCERN_COMMANDS: Final[frozenset[str]] = frozenset({
    "bulkWrite", "collMod", "create", "createIndexes", "delete", "drop",
    "dropAllUsersFromDatabase", "dropDatabase", "dropIndexes", "dropUser",
    "findAndModify", "insert", "renameCollection", "update",
})


def supports_write_concern(command: dict[str, Any]) -> bool:
    """Return whether the command accepts a write concern document."""
    return command_name(command) in _WRITE_CONCERN_COMMANDS


def command_name(command: dict[str, Any]) -> str:
    """Return the first command key, or an empty string.

    Returns:
        The command name.
    """
    return next(iter(command), "")


def is_cursor_command(command: dict[str, Any]) -> bool:
    """Whether a command continues or kills a cursor.

    Returns:
        ``True`` for ``getMore`` and ``killCursors``.
    """
    return command_name(command) in _CURSOR_COMMANDS


def is_read_command(command: dict[str, Any]) -> bool:
    """Whether a command may use a non-primary read preference.

    Returns:
        ``True`` when the command may be routed to a secondary.
    """
    name = command_name(command)
    if name == "explain":
        nested = command.get("explain", {})
        return is_read_command(nested)
    if name == "aggregate":
        return not any(
            "$out" in stage or "$merge" in stage
            for stage in command.get("pipeline", [])
            if isinstance(stage, dict)
        )
    return name in _READ_COMMANDS
