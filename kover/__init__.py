"""Async MongoDB client, operations, and Pydantic document models."""

# Copyright (c) 2024 megawattka
# SPDX-License-Identifier: Apache-2.0

from ._utils import (
    CompressionContext,
    ExcludeIfNone,
    chain,
    classrepr,
    filter_non_null,
    maybe_to_dict,
    raw_decoder,
)
from .bootstrap import from_uri, make_client
from .bulk_write_builder import BulkWriteBuilder
from .client import Kover
from .collection import Collection
from .cursor import Cursor
from .database import Database
from .exceptions import (
    ConnectionClosedError,
    DriverError,
    InvalidOperationError,
    NetworkError,
    OperationFailure,
    PoolClosedError,
    PoolPausedError,
    PoolTimeoutError,
    ProtocolError,
    ServerSelectionError,
)
from .execution import CommandExecutor
from .gridfs import (
    Chunk,
    File,
    GridFS,
    GridFSFileNotFound,
    IncorrectGridFSData,
)
from .models import (
    Address,
    AuthCredentials,
    BuildInfo,
    Collation,
    CollationStrength,
    Delete,
    Index,
    IndexDirection,
    IndexType,
    ReadConcern,
    ReadPreference,
    ReplicaSetConfig,
    ReplicaSetConfigSettings,
    ReplicaSetMember,
    TxnState,
    Update,
    ValidationLevel,
    WriteConcern,
)
from .network import (
    Authenticator,
    Connection,
    ConnectionFactory,
    ConnectionLease,
    ConnectionPool,
    Handshake,
    HelloResult,
    Transport,
)
from .schema import Document, MongoDBSchemaGenerator
from .session import Session
from .topology import (
    ServerDescription,
    ServerType,
    TopologyMonitor,
    TopologyType,
    TopologyVersion,
)

__all__ = (
    "Address",
    "AuthCredentials",
    "Authenticator",
    "BuildInfo",
    "BulkWriteBuilder",
    "Chunk",
    "Collation",
    "CollationStrength",
    "Collection",
    "CommandExecutor",
    "CompressionContext",
    "Connection",
    "ConnectionClosedError",
    "ConnectionFactory",
    "ConnectionLease",
    "ConnectionPool",
    "Cursor",
    "Database",
    "Delete",
    "Document",
    "DriverError",
    "ExcludeIfNone",
    "File",
    "GridFS",
    "GridFSFileNotFound",
    "Handshake",
    "HelloResult",
    "IncorrectGridFSData",
    "Index",
    "IndexDirection",
    "IndexType",
    "InvalidOperationError",
    "Kover",
    "MongoDBSchemaGenerator",
    "NetworkError",
    "OperationFailure",
    "PoolClosedError",
    "PoolPausedError",
    "PoolTimeoutError",
    "ProtocolError",
    "ReadConcern",
    "ReadPreference",
    "ReplicaSetConfig",
    "ReplicaSetConfigSettings",
    "ReplicaSetMember",
    "ServerDescription",
    "ServerSelectionError",
    "ServerType",
    "Session",
    "TopologyMonitor",
    "TopologyType",
    "TopologyVersion",
    "Transport",
    "TxnState",
    "Update",
    "ValidationLevel",
    "WriteConcern",
    "chain",
    "classrepr",
    "filter_non_null",
    "from_uri",
    "make_client",
    "maybe_to_dict",
    "raw_decoder",
)
