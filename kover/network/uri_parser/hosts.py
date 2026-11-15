"""Parse TCP addresses shared by URI parsing and topology discovery."""

from __future__ import annotations

from ipaddress import IPv6Address
import re
from urllib.parse import unquote_plus

_DEFAULT_PORT = 27017
_MAX_PORT = 65535
_ASCII_SPACE = 32
_ASCII_DELETE = 127


def has_control_characters(value: str) -> bool:
    """Return whether a string contains ASCII control characters."""
    return any(
        ord(char) < _ASCII_SPACE or ord(char) == _ASCII_DELETE
        for char in value
    )


def decode_component(value: str) -> str:
    """Decode a URI component, rejecting invalid escapes and UTF-8.

    Returns:
        The decoded component.

    Raises:
        ValueError: If the component contains invalid escapes or NUL.
    """
    if re.search(r"%(?![0-9a-fA-F]{2})", value):
        msg = "Invalid percent escape in MongoDB URI"
        raise ValueError(msg)

    try:
        decoded = unquote_plus(value, errors="strict")
    except UnicodeError as error:
        msg = "Invalid UTF-8 in MongoDB URI"
        raise ValueError(msg) from error

    if "\x00" in decoded:
        msg = "NUL is not allowed in MongoDB URI components"
        raise ValueError(msg)

    return decoded


def _split_host(value: str) -> tuple[str, str | None]:
    port_text: str | None = None
    if value.startswith("["):
        host, bracket, suffix = value[1:].partition("]")
        if not bracket or (suffix and not suffix.startswith(":")):
            msg = "Invalid bracketed IPv6 address"
            raise ValueError(msg)

        try:
            IPv6Address(host)
        except ValueError as error:
            msg = "Invalid IPv6 address"
            raise ValueError(msg) from error

        if suffix:
            port_text = suffix[1:]
    else:
        if value.count(":") > 1:
            msg = "IPv6 addresses must be enclosed in brackets"
            raise ValueError(msg)

        host, separator, port = value.partition(":")
        if separator:
            port_text = port

        if any(char in host for char in "[]%"):
            msg = "Invalid hostname"
            raise ValueError(msg)

    return host, port_text


def _parse_port(port_text: str | None, default_port: int) -> int:
    port_number = default_port
    if port_text is not None:
        if not port_text.isascii() or not port_text.isdecimal():
            msg = "Port must be an integer between 1 and 65535"
            raise ValueError(msg)

        try:
            port_number = int(port_text)
        except ValueError as error:
            msg = "Port must be an integer between 1 and 65535"
            raise ValueError(
                msg,
            ) from error

    if not 1 <= port_number <= _MAX_PORT:
        msg = "Port must be an integer between 1 and 65535"
        raise ValueError(msg)

    return port_number


def parse_host(
    value: str,
    default_port: int = _DEFAULT_PORT,
) -> tuple[str, int]:
    """Parse a decoded hostname, IPv4 address, or bracketed IPv6 address.

    Unix sockets are deliberately unsupported. This function also accepts
    addresses advertised by a server, which are not percent-decoded.

    Returns:
        A lowercase hostname and validated TCP port.

    Raises:
        ValueError: If the address is empty, malformed, or a Unix socket.
    """
    if "/" in value or "\\" in value:
        msg = "Unix domain sockets are not supported"
        raise ValueError(msg)
    if (
        not value
        or has_control_characters(value)
        or any(char.isspace() for char in value)
    ):
        msg = "Host must be nonempty and contain no whitespace"
        raise ValueError(msg)

    host, port_text = _split_host(value)
    if host.lower().endswith(".sock"):
        msg = "Unix domain sockets are not supported"
        raise ValueError(msg)

    if not host or any(char in host for char in "@,/?#\x00"):
        msg = "Invalid hostname"
        raise ValueError(msg)

    return host.lower(), _parse_port(port_text, default_port)
