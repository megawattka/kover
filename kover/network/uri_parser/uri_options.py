"""Validation and normalization of MongoDB URI options."""

from __future__ import annotations

import math
import re
from typing import Any

from ...models.read_preference import ReadPreference
from .hosts import decode_component

_BOOLEANS = {
    "directConnection",
    "loadBalanced",
    "tls",
    "journal",
    "retryReads",
    "retryWrites",
    "tlsAllowInvalidCertificates",
    "tlsAllowInvalidHostnames",
    "tlsInsecure",
    "tlsDisableOCSPEndpointCheck",
    "tlsDisableCertificateRevocationCheck",
    "serverSelectionTryOnce",
}
_INTEGERS = {
    "maxPoolSize": 0,
    "minPoolSize": 0,
    "maxConnecting": 1,
    "srvMaxHosts": 0,
    "wTimeoutMS": 0,
    "zlibCompressionLevel": -1,
    "maxStalenessSeconds": -1,
}
_TIMEOUTS = {
    "connectTimeoutMS",
    "socketTimeoutMS",
    "serverSelectionTimeoutMS",
    "waitQueueTimeoutMS",
    "heartbeatFrequencyMS",
    "maxIdleTimeMS",
    "timeoutMS",
}
_STRINGS = {
    "appname",
    "authSource",
    "authMechanism",
    "replicaSet",
    "readPreference",
    "readConcernLevel",
    "srvServiceName",
    "tlsCAFile",
    "tlsCertificateKeyFile",
    "tlsCertificateKeyFilePassword",
    "uuidRepresentation",
    "serverMonitoringMode",
}
_SPECIAL = {
    "w",
    "readPreferenceTags",
    "authMechanismProperties",
    "compressors",
    "localThresholdMS",
}
_CANONICAL = {
    key.lower(): key
    for key in _BOOLEANS | _INTEGERS.keys() | _TIMEOUTS | _STRINGS | _SPECIAL
}
_CANONICAL.update(ssl="tls", wtimeout="wTimeoutMS", j="journal")
_AUTH_MECHANISMS = {
    "DEFAULT",
    "SCRAM-SHA-1",
    "SCRAM-SHA-256",
    "MONGODB-X509",
    "MONGODB-AWS",
    "GSSAPI",
    "PLAIN",
    "MONGODB-OIDC",
}
_MAX_ZLIB_LEVEL = 9
_MIN_HEARTBEAT_MS = 500
_MAX_APPNAME_BYTES = 128
_ENUMS = {
    "uuidRepresentation": {
        "standard",
        "pythonLegacy",
        "javaLegacy",
        "csharpLegacy",
        "unspecified",
    },
    "serverMonitoringMode": {"auto", "poll", "stream"},
    "readConcernLevel": {
        "local",
        "available",
        "majority",
        "linearizable",
        "snapshot",
    },
}
type _OptionValue = (
    bool | int | float | str | list[str] | dict[str, str | bool]
)


def _boolean(key: str, value: str) -> bool:
    if value not in {"true", "false"}:
        raise ValueError(f"{key} must be 'true' or 'false'")

    return value == "true"


def _integer(key: str, value: str, minimum: int) -> int:
    if not re.fullmatch(r"-?[0-9]+", value):
        raise ValueError(f"{key} must be an integer")

    result = int(value)
    if result < minimum:
        raise ValueError(f"{key} must be >= {minimum}")

    return result


def _milliseconds(key: str, value: str) -> float:
    if not re.fullmatch(
        r"[+]?(?:[0-9]+(?:\.[0-9]*)?|\.[0-9]+)(?:[eE][+-]?[0-9]+)?",
        value,
    ):
        raise ValueError(f"{key} must be a finite nonnegative number")

    try:
        result = float(value)
    except ValueError as error:
        raise ValueError(
            f"{key} must be a finite nonnegative number",
        ) from error

    if not math.isfinite(result) or result < 0:
        raise ValueError(f"{key} must be a finite nonnegative number")

    return result


def _pairs(key: str, value: str) -> dict[str, str]:
    result: dict[str, str] = {}
    if not value:
        return result

    for item in value.split(","):
        name, separator, content = item.partition(":")
        if not separator or not name or name in result:
            raise ValueError(f"{key} requires unique key:value pairs")

        result[name] = content

    return result


def _option(key: str, value: str) -> _OptionValue:  # ruff: ignore[too-many-return-statements, complex-structure, too-many-branches]
    if key in _BOOLEANS:
        return _boolean(key, value)

    if key in _INTEGERS:
        number = _integer(key, value, _INTEGERS[key])
        if key == "zlibCompressionLevel" and number > _MAX_ZLIB_LEVEL:
            raise ValueError("zlibCompressionLevel must be between -1 and 9")
        return number

    if key in _TIMEOUTS:
        milliseconds = _milliseconds(key, value)
        if key == "heartbeatFrequencyMS" and milliseconds < _MIN_HEARTBEAT_MS:
            raise ValueError("heartbeatFrequencyMS must be >= 500")
        return milliseconds / 1000

    if key == "localThresholdMS":
        return _milliseconds(key, value)

    if key == "w":
        if not value:
            raise ValueError("w must not be empty")

        return (
            _integer(key, value, 0)
            if re.fullmatch(r"-?[0-9]+", value)
            else value
        )
    if key in {"readPreferenceTags", "authMechanismProperties"}:
        pairs: dict[str, str | bool] = dict(_pairs(key, value))
        if (
            key == "authMechanismProperties"
            and "CANONICALIZE_HOST_NAME" in pairs
        ):
            canonicalize = pairs["CANONICALIZE_HOST_NAME"]
            if isinstance(canonicalize, str) and canonicalize in {
                "true",
                "false",
            }:
                pairs["CANONICALIZE_HOST_NAME"] = _boolean(key, canonicalize)
        return pairs

    if key == "compressors":
        compressors = value.split(",") if value else []
        if set(compressors) - {"snappy", "zlib", "zstd"}:
            raise ValueError(
                "compressors must contain only snappy, zlib, zstd",
            )
        return compressors

    if not value:
        raise ValueError(f"{key} must not be empty")

    if key == "appname" and len(value.encode("utf-8")) > _MAX_APPNAME_BYTES:
        raise ValueError("appName must be at most 128 UTF-8 bytes")

    if key == "authMechanism" and value not in _AUTH_MECHANISMS:
        raise ValueError("Unsupported authMechanism")

    if key in _ENUMS and value not in _ENUMS[key]:
        raise ValueError(f"Unsupported {key}")

    if key == "srvServiceName" and not re.fullmatch(
        r"[a-zA-Z0-9][a-zA-Z0-9-]*",
        value,
    ):
        raise ValueError("Invalid srvServiceName")

    return value


def parse_options(query: str, *, txt: bool = False) -> dict[str, Any]:
    """Parse case-insensitive options into canonical, typed keys.

    Duplicates are rejected, except ordered readPreferenceTags. Unknown
    options are rejected rather than silently hiding configuration mistakes.

    Returns:
        Normalized options. Most MS timeouts become seconds; localThresholdMS
        and wTimeoutMS retain milliseconds for the composition layer.

    Raises:
        ValueError: If an option is unknown, duplicated, or malformed.
    """
    options: dict[str, Any] = {}
    if not query:
        return options

    if "&" in query and ";" in query:
        raise ValueError("Cannot mix '&' and ';' option separators")

    for item in re.split(r"[&;]", query):
        name, separator, raw = item.partition("=")
        if not separator or not name:
            raise ValueError("URI options must be key=value pairs")

        key = _CANONICAL.get(decode_component(name).lower())
        if key is None:
            raise ValueError("Unknown MongoDB URI option")

        if txt and key not in {"authSource", "replicaSet", "loadBalanced"}:
            raise ValueError(
                "TXT records may only set "
                "authSource, replicaSet, loadBalanced",
            )

        value = _option(key, decode_component(raw))
        if key == "readPreferenceTags":
            options.setdefault(key, []).append(value)

        elif key in options:
            raise ValueError(f"Duplicate URI option: {key}")
        else:
            options[key] = value

    return options


def validate_options(
    options: dict[str, Any],
    node_count: int,
    *,
    srv: bool,
) -> None:
    """Validate relationships between parsed URI options.

    Raises:
        ValueError: If options contradict each other or the seed list.
    """
    if options.get("directConnection") and (srv or node_count != 1):
        raise ValueError("directConnection=true requires one non-SRV host")

    if options.get("loadBalanced") and (
        node_count != 1
        or options.get("directConnection")
        or "replicaSet" in options
    ):
        raise ValueError(
            "loadBalanced=true requires one host "
            "and no replicaSet/directConnection",
        )

    if not srv and {"srvMaxHosts", "srvServiceName"} & options.keys():
        raise ValueError("srvMaxHosts and srvServiceName require mongodb+srv")

    if options.get("srvMaxHosts") and (
        options.get("replicaSet") or options.get("loadBalanced")
    ):
        raise ValueError(
            "srvMaxHosts cannot be combined with replicaSet or loadBalanced",
        )

    if options.get("minPoolSize", 0) > options.get("maxPoolSize", 100) != 0:
        raise ValueError("minPoolSize cannot exceed maxPoolSize")

    if options.get("w") == 0 and options.get("journal"):
        raise ValueError("w=0 cannot be combined with journal=true")

    ReadPreference(
        mode=options.get("readPreference", "primary"),
        tag_sets=tuple(options["readPreferenceTags"])
        if "readPreferenceTags" in options
        else None,
        max_staleness_seconds=options.get("maxStalenessSeconds", -1),
    )

    if options.get("tlsInsecure") and (
        "tlsAllowInvalidCertificates" in options
        or "tlsAllowInvalidHostnames" in options
    ):
        raise ValueError(
            "tlsInsecure conflicts with explicit TLS validation options",
        )
