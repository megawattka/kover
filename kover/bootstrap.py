"""Compose v2 clients from explicit connection parameters or a MongoDB URI."""

from __future__ import annotations

from typing import TYPE_CHECKING, Any

from .client import Kover
from .execution.executor import CommandExecutor
from .models.address import Address
from .models.concerns import WriteConcern
from .models.options import DiscoveryOptions
from .models.read_preference import ReadPreference
from .network.factory import ConnectionFactory
from .network.probe import ServerProbe
from .network.registry import PoolRegistry
from .network.uri_parser import parse_uri
from .topology.discovery import ServerDiscovery
from .topology.selector import ServerSelector

if TYPE_CHECKING:
    import asyncio
    from collections.abc import Sequence

    from bson import CodecOptions

    from .models.credentials import AuthCredentials


async def _build_client(
    seeds: list[Address],
    *,
    options: DiscoveryOptions,
    write_concern: WriteConcern,
    credentials: AuthCredentials | None,
    tls: bool,
    compression: Sequence[str] | None,
    zlib_compression_level: int,
    application: dict[str, Any] | None,
    loop: asyncio.AbstractEventLoop | None,
    max_pool_size: int,
    codec_options: CodecOptions | None = None,
) -> Kover:
    factory = ConnectionFactory(
        credentials=credentials,
        tls=tls,
        compression=list(compression) if compression is not None else None,
        zlib_compression_level=zlib_compression_level,
        application=application,
        loop=loop,
        codec_options=codec_options,
    )
    discovery = ServerDiscovery(
        seeds,
        options=options,
        probe=ServerProbe(factory),
    )
    selector = ServerSelector(discovery, options=options)
    pools = PoolRegistry(
        factory,
        max_pool_size=max_pool_size,
        connection_timeout=options.connect_timeout,
    )
    executor = CommandExecutor(
        selector=selector,
        pools=pools,
        default_preference=options.read_preference,
    )
    selected = False
    try:
        await selector.select(options.read_preference)
        selected = True
    finally:
        # Also clean up if initial selection is cancelled by the caller.
        if not selected:
            await executor.close()
    return Kover(executor, write_concern=write_concern)


async def make_client(
    host: str = "127.0.0.1",
    port: int = 27017,
    *,
    credentials: AuthCredentials | None = None,
    loop: asyncio.AbstractEventLoop | None = None,
    compression: Sequence[str] | None = None,
    zlib_compression_level: int = -1,
    tls: bool = False,
    application: dict[str, Any] | None = None,
    w: str | int = "majority",
    replica_set: str | None = None,
    direct_connection: bool = False,
    server_selection_timeout: float = 30.0,
    connect_timeout: float | None = 10.0,
    read_preference: ReadPreference | None = None,
    local_threshold: float = 0.015,
    max_pool_size: int = 100,
    write_concern: WriteConcern | None = None,
    codec_options: CodecOptions | None = None,
) -> Kover:
    """Build a client and verify initial server selection.

    Timeout and latency values are seconds. An explicit ``write_concern``
    takes precedence over ``w``. The returned client owns its executor/pools.
    ``zlib_compression_level`` ranges from -1 (zlib default) to 9.

    Returns:
        A client ready to execute commands against the selected deployment.
    """
    return await _build_client(
        [Address(host=host, port=port)],
        options=DiscoveryOptions(
            replica_set=replica_set,
            direct_connection=direct_connection,
            server_selection_timeout=server_selection_timeout,
            connect_timeout=connect_timeout,
            read_preference=read_preference or ReadPreference(),
            local_threshold=local_threshold,
        ),
        write_concern=write_concern or WriteConcern(w=w),
        credentials=credentials,
        tls=tls,
        compression=compression,
        zlib_compression_level=zlib_compression_level,
        application=application,
        loop=loop,
        max_pool_size=max_pool_size,
        codec_options=codec_options,
    )


async def from_uri(
    uri: str,
    loop: asyncio.AbstractEventLoop | None = None,
    codec_options: CodecOptions | None = None,
) -> Kover:
    """Build a client from all URI seeds and verify initial server selection.

    Returns:
        A client with the URI's authentication and concern settings.

    Raises:
        ValueError: If load-balanced mode is requested; it is not supported.
    """
    parsed = await parse_uri(uri)
    values = parsed.options
    if values.get("loadBalanced", False):
        raise ValueError("loadBalanced=true is not supported")

    return await _build_client(
        [Address(host=host, port=port) for host, port in parsed.node_list],
        options=DiscoveryOptions(
            replica_set=values.get("replicaSet"),
            direct_connection=values.get("directConnection", False),
            # The URI parser normalizes these two timeouts to seconds.
            server_selection_timeout=values.get(
                "serverSelectionTimeoutMS",
                30.0,
            ),
            connect_timeout=values.get("connectTimeoutMS", 10.0) or None,
            read_preference=ReadPreference(
                mode=values.get("readPreference", "primary"),
                tag_sets=(
                    tuple(values["readPreferenceTags"])
                    if "readPreferenceTags" in values
                    else None
                ),
                max_staleness_seconds=values.get("maxStalenessSeconds", -1),
            ),
            local_threshold=values.get("localThresholdMS", 15) / 1000,
        ),
        write_concern=WriteConcern(
            w=values.get("w", "majority"),
            j=values.get("journal"),
            wtimeout=values.get("wTimeoutMS", 0),
        ),
        credentials=parsed.credentials,
        tls=values.get("tls", False),
        compression=values.get("compressors"),
        zlib_compression_level=values.get("zlibCompressionLevel", -1),
        application=(
            {"name": values["appname"]} if "appname" in values else None
        ),
        loop=loop,
        max_pool_size=values.get("maxPoolSize", 100),
        codec_options=codec_options,
    )
