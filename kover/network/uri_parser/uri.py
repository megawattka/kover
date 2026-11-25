"""Uri parser functionality for Kover."""

from __future__ import annotations

from .hosts import decode_component, has_control_characters, parse_host
from .models import ParsedUri
from .srv import limit_srv_hosts, resolve_srv, validate_srv_host
from .uri_options import parse_options, validate_options


def _userinfo(authority: str) -> tuple[str, str | None, str | None]:
    if "@" not in authority:
        return authority, None, None

    userinfo, _, hosts = authority.rpartition("@")
    username, separator, password = userinfo.partition(":")
    if not username or "@" in userinfo or ":" in password:
        msg = "Username and password must escape reserved URI characters"
        raise ValueError(
            msg,
        )

    for component in (username, password):
        if any(char in component for char in "$:/?#[]@"):
            msg = "Username and password must escape reserved URI characters"
            raise ValueError(
                msg,
            )

    return (
        hosts,
        decode_component(username),
        decode_component(password) if separator else None,
    )


def _namespace(path: str) -> tuple[str | None, str | None]:
    if not path:
        return None, None

    namespace = decode_component(path)
    database, separator, collection = namespace.partition(".")
    if not database or any(char in database for char in '/\\ "$.'):
        msg = "Invalid database name in MongoDB URI"
        raise ValueError(msg)

    if "/" in namespace or "\\" in namespace:
        msg = "MongoDB URI must contain only one database path segment"
        raise ValueError(
            msg,
        )

    return database, collection if separator else None


def _seeds(
    hosts: str,
    *,
    srv: bool,
) -> tuple[list[tuple[str, int]], str | None]:
    raw_hosts = hosts.split(",")
    nodes = [parse_host(decode_component(host)) for host in raw_hosts]
    if not srv:
        return nodes, None

    if len(raw_hosts) != 1 or ":" in decode_component(raw_hosts[0]):
        msg = "mongodb+srv requires exactly one hostname without a port"
        raise ValueError(
            msg,
        )

    fqdn = nodes[0][0].rstrip(".")
    validate_srv_host(fqdn)
    return nodes, fqdn


def _split_uri(uri: str) -> tuple[str, str, str, str]:
    scheme, separator, remainder = uri.partition("://")
    if not separator or scheme not in {"mongodb", "mongodb+srv"}:
        msg = "URI must begin with mongodb:// or mongodb+srv://"
        raise ValueError(msg)

    if "#" in remainder or has_control_characters(uri):
        msg = (
            "Fragments and control characters are not allowed in MongoDB URIs"
        )
        raise ValueError(
            msg,
        )

    location, _, query = remainder.partition("?")
    authority, slash, path = location.partition("/")
    if not authority and slash:
        msg = "Unix domain sockets are not supported"
        raise ValueError(msg)

    return scheme, authority, path, query


async def parse_uri(uri: str) -> ParsedUri:
    """Parse a MongoDB URI without connecting to MongoDB.

    Supports TCP seed lists, bracketed IPv6, percent-encoded credentials,
    typed case-insensitive options, and asynchronous SRV/TXT discovery.
    Unix sockets, fragments, unknown options and duplicate scalar options
    are rejected. DNS is only queried for ``mongodb+srv://`` URIs.
    Invalid syntax, options, addresses or DNS records raise ``ValueError``.

    Returns:
        Parsed URI with canonical option keys. Timeout normalization matches
        the units consumed by :func:`kover.bootstrap.from_uri`.

    """
    scheme, authority, path, query = _split_uri(uri)
    hosts, username, password = _userinfo(authority)
    database, collection = _namespace(path)
    options = parse_options(query)
    srv = scheme == "mongodb+srv"
    nodes, fqdn = _seeds(hosts, srv=srv)
    validate_options(options, len(nodes), srv=srv)

    if fqdn is not None:
        nodes, txt_options = await resolve_srv(fqdn, options)
        options = {**txt_options, **options}
        options.setdefault("tls", True)
        validate_options(options, len(nodes), srv=True)
        nodes = limit_srv_hosts(nodes, options.get("srvMaxHosts", 0))

    return ParsedUri(
        nodelist=nodes,
        username=username,
        password=password,
        database=database,
        collection=collection,
        options=options,
        fqdn=fqdn,
    )
