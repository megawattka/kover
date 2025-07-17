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

__version__ = "2.1.1"
__author__ = "oMegaPB"
__license__ = "MIT"
__copyright__ = "Copyright (C) 2024-present megawattka"

from .client import Kover
from .collection import Collection
from .cursor import Cursor
from .database import Database
from .enums import (
    CollationStrength,
    IndexDirection,
    IndexType,
    ValidationLevel,
)
from .exceptions import (
    CorruptedDocument,
    CredentialsException,
    OperationFailure,
    SchemaGenerationException,
)
from .models import (
    BuildInfo,
    Collation,
    Delete,
    HelloResult,
    Index,
    ReadConcern,
    ReplicaSetConfig,
    ReplicaSetConfigSettings,
    ReplicaSetMember,
    Update,
    User,
    WriteConcern,
)
from .network import AuthCredentials
from .schema import Document, SchemaGenerator
from .session import Session, Transaction
from .typings import xJsonT
from .utils import HasToDict, chain, filter_non_null, maybe_to_dict

__all__ = [
    "AuthCredentials",
    "BuildInfo",
    "Collation",
    "CollationStrength",
    "Collection",
    "CorruptedDocument",
    "CredentialsException",
    "Cursor",
    "Database",
    "Delete",
    "Document",
    "HasToDict",
    "HelloResult",
    "Index",
    "IndexDirection",
    "IndexType",
    "Kover",
    "OperationFailure",
    "ReadConcern",
    "ReplicaSetConfig",
    "ReplicaSetConfigSettings",
    "ReplicaSetMember",
    "SchemaGenerationException",
    "SchemaGenerator",
    "Session",
    "Transaction",
    "Update",
    "User",
    "ValidationLevel",
    "WriteConcern",
    "chain",
    "filter_non_null",
    "maybe_to_dict",
    "xJsonT",
]
