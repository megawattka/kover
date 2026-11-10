# MIT License

# Copyright (c) 2024 megawattka

# Permission is hereby granted, free of charge, to any person obtaining a copy
# of this software and associated documentation files (the "Software"), to deal
# in the Software without restriction, including without limitation the rights
# to use, copy, modify, merge, publish, distribute, sublicense, and/or sell
# copies of the Software, and to permit persons to whom the Software is
# furnished to do so, subject to the following conditions:

# The above copyright notice and this permission notice shall be included in
# all copies or substantial portions of the Software.

# THE SOFTWARE IS PROVIDED "AS IS", WITHOUT WARRANTY OF ANY KIND, EXPRESS OR
# IMPLIED, INCLUDING BUT NOT LIMITED TO THE WARRANTIES OF MERCHANTABILITY,
# FITNESS FOR A PARTICULAR PURPOSE AND NONINFRINGEMENT. IN NO EVENT SHALL THE
# AUTHORS OR COPYRIGHT HOLDERS BE LIABLE FOR ANY CLAIM, DAMAGES OR OTHER
# LIABILITY, WHETHER IN AN ACTION OF CONTRACT, TORT OR OTHERWISE, ARISING FROM,
# OUT OF OR IN CONNECTION WITH THE SOFTWARE OR THE USE OR OTHER DEALINGS IN THE
# SOFTWARE.

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
    HelloResult,
    Index,
    IndexDirection,
    IndexType,
    ReadConcern,
    ReadPreference,
    ReplicaSetConfig,
    ReplicaSetConfigSettings,
    ReplicaSetMember,
    ServerDescription,
    ServerType,
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
    Transport,
)
from .schema import Document, MongoDBSchemaGenerator
from .session import Session

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
