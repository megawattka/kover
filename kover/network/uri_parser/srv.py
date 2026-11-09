"""Asynchronous MongoDB seed-list discovery using dnspython."""

from __future__ import annotations

from ipaddress import ip_address
from random import SystemRandom
from typing import TYPE_CHECKING, Any, cast

import dns.asyncresolver
from dns.exception import DNSException
from dns.resolver import NXDOMAIN, NoAnswer

from .hosts import parse_host
from .uri_options import parse_options

if TYPE_CHECKING:
    from dns.rdtypes.ANY.TXT import TXT
    from dns.rdtypes.IN.SRV import SRV

_MIN_DOMAIN_LABELS = 2
_MAX_LABEL_LENGTH = 63
_MAX_DOMAIN_LENGTH = 253


def validate_srv_host(host: str) -> str:
    """Validate an SRV seed and return the allowed parent domain.

    Returns:
        The domain to which all SRV targets must belong.

    Raises:
        ValueError: If the seed is an IP address or not a DNS name.
    """
    try:
        ip_address(host)
    except ValueError:
        pass
    else:
        raise ValueError(
            "mongodb+srv requires a DNS hostname, not an IP address",
        )
    labels = host.rstrip(".").split(".")
    if (
        len(host) > _MAX_DOMAIN_LENGTH
        or len(labels) < _MIN_DOMAIN_LABELS
        or any(
            not label
            or len(label) > _MAX_LABEL_LENGTH
            or label.startswith("-")
            or label.endswith("-")
            or not all(
                char.isascii() and (char.isalnum() or char == "-")
                for char in label
            )
            for label in labels
        )
    ):
        raise ValueError(
            "mongodb+srv requires a valid DNS hostname with a domain",
        )
    return ".".join(labels[1:] if len(labels) > _MIN_DOMAIN_LABELS else labels)


async def resolve_srv(
    host: str,
    options: dict[str, Any],
) -> tuple[list[tuple[str, int]], dict[str, Any]]:
    """Resolve SRV and optional TXT records without blocking the event loop.

    Returns:
        All validated SRV nodes and TXT-provided options. Host limiting is
        applied separately, after validating TXT/URI option combinations.

    Raises:
        ValueError: If DNS fails or records violate MongoDB's discovery rules.
    """
    parent = validate_srv_host(host)
    lifetime = options.get("connectTimeoutMS") or 20.0
    service = options.get("srvServiceName", "mongodb")
    try:
        answer = await dns.asyncresolver.resolve(
            f"_{service}._tcp.{host}",
            "SRV",
            lifetime=lifetime,
            search=False,
        )
    except DNSException as error:
        raise ValueError("Unable to resolve MongoDB SRV records") from error

    nodes: list[tuple[str, int]] = []
    for record in answer:
        srv = cast("SRV", record)
        target = srv.target.to_text(omit_final_dot=True).lower()
        if not target.endswith(f".{parent}"):
            raise ValueError("SRV target is outside the seed's parent domain")
        node = parse_host(f"{target}:{srv.port}")
        if node not in nodes:
            nodes.append(node)

    if not nodes:
        raise ValueError("MongoDB SRV response contains no hosts")

    return nodes, await _resolve_txt(host, lifetime)


async def _resolve_txt(host: str, lifetime: float) -> dict[str, Any]:
    try:
        txt_answer = await dns.asyncresolver.resolve(
            host,
            "TXT",
            lifetime=lifetime,
            search=False,
        )
    except (NoAnswer, NXDOMAIN):
        return {}

    except DNSException as error:
        raise ValueError("Unable to resolve MongoDB TXT records") from error

    if len(txt_answer) > 1:
        raise ValueError("Only one MongoDB TXT record is allowed")

    txt_options: dict[str, Any] = {}
    for record in txt_answer:
        txt = cast("TXT", record)
        try:
            text = b"".join(txt.strings).decode("utf-8")
        except UnicodeError as error:
            raise ValueError(
                "MongoDB TXT record is not valid UTF-8",
            ) from error
        txt_options = parse_options(text, txt=True)

    return txt_options


def limit_srv_hosts(
    nodes: list[tuple[str, int]],
    maximum: int,
) -> list[tuple[str, int]]:
    """Return a random subset when srvMaxHosts limits the seed list."""
    if maximum and maximum < len(nodes):
        return SystemRandom().sample(nodes, maximum)

    return nodes
