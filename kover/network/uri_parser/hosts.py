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
        raise ValueError("Invalid percent escape in MongoDB URI")

    try:
        decoded = unquote_plus(value, errors="strict")
    except UnicodeError as error:
        raise ValueError("Invalid UTF-8 in MongoDB URI") from error

    if "\x00" in decoded:
        raise ValueError("NUL is not allowed in MongoDB URI components")

    return decoded


def _split_host(value: str) -> tuple[str, str | None]:
    port_text: str | None = None
    if value.startswith("["):
        host, bracket, suffix = value[1:].partition("]")
        if not bracket or (suffix and not suffix.startswith(":")):
            raise ValueError("Invalid bracketed IPv6 address")

        try:
            IPv6Address(host)
        except ValueError as error:
            raise ValueError("Invalid IPv6 address") from error

        if suffix:
            port_text = suffix[1:]
    else:
        if value.count(":") > 1:
            raise ValueError("IPv6 addresses must be enclosed in brackets")

        host, separator, port = value.partition(":")
        if separator:
            port_text = port

        if any(char in host for char in "[]%"):
            raise ValueError("Invalid hostname")

    return host, port_text


def _parse_port(port_text: str | None, default_port: int) -> int:
    port_number = default_port
    if port_text is not None:
        if not port_text.isascii() or not port_text.isdecimal():
            raise ValueError("Port must be an integer between 1 and 65535")

        try:
            port_number = int(port_text)
        except ValueError as error:
            raise ValueError(
                "Port must be an integer between 1 and 65535",
            ) from error

    if not 1 <= port_number <= _MAX_PORT:
        raise ValueError("Port must be an integer between 1 and 65535")

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
        raise ValueError("Unix domain sockets are not supported")
    if (
        not value
        or has_control_characters(value)
        or any(char.isspace() for char in value)
    ):
        raise ValueError("Host must be nonempty and contain no whitespace")

    host, port_text = _split_host(value)
    if host.lower().endswith(".sock"):
        raise ValueError("Unix domain sockets are not supported")

    if not host or any(char in host for char in "@,/?#\x00"):
        raise ValueError("Invalid hostname")

    return host.lower(), _parse_port(port_text, default_port)
