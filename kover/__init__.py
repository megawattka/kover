# MIT License

# Copyright (c) 2024 oMegaPB

# Permission is hereby granted, free of charge, to any person obtaining a copy
# of this software and associated documentation files (the "Software"), to deal
# in the Software without restriction, including without limitation the rights
# to use, copy, modify, merge, publish, distribute, sublicense, and/or sell
# copies of the Software, and to permit persons to whom the Software is
# furnished to do so, subject to the following conditions:

# The above copyright notice and this permission notice shall be included in all # noqa: E501
# copies or substantial portions of the Software.

# THE SOFTWARE IS PROVIDED "AS IS", WITHOUT WARRANTY OF ANY KIND, EXPRESS OR
# IMPLIED, INCLUDING BUT NOT LIMITED TO THE WARRANTIES OF MERCHANTABILITY,
# FITNESS FOR A PARTICULAR PURPOSE AND NONINFRINGEMENT. IN NO EVENT SHALL THE
# AUTHORS OR COPYRIGHT HOLDERS BE LIABLE FOR ANY CLAIM, DAMAGES OR OTHER
# LIABILITY, WHETHER IN AN ACTION OF CONTRACT, TORT OR OTHERWISE, ARISING FROM,
# OUT OF OR IN CONNECTION WITH THE SOFTWARE OR THE USE OR OTHER DEALINGS IN THE
# SOFTWARE.

__version__ = "2.0.8"
__author__ = "oMegaPB"
__license__ = "MIT"
__copyright__ = "Copyright (C) 2024-present oMegaPB <https://github.com/oMegaPB>"  # noqa: E501

from .auth import AuthCredentials
from .client import Kover
from .collection import Collection
from .cursor import Cursor
from .database import Database
from .enums import (
    ValidationLevel,
    IndexDirection,
    IndexType,
    CollationStrength
)
from .exceptions import (
    OperationFailure,
    SchemaGenerationException,
    CorruptedDocument,
    CredentialsException
)
from .models import (
    Update,
    Delete,
    ReadConcern,
    WriteConcern,
    Collation,
    Index,
    User,
    BuildInfo,
    HelloResult
)
from .schema import SchemaGenerator, Document
from .session import Session, Transaction
from .typings import xJsonT
from .utils import (
    HasToDict,
    chain,
    filter_non_null,
    maybe_to_dict
)

__all__ = [
    "AuthCredentials",
    "Kover",
    "Collection",
    "Cursor",
    "Database",
    "ValidationLevel",
    "IndexDirection",
    "IndexType",
    "CollationStrength",
    "OperationFailure",
    "SchemaGenerationException",
    "CorruptedDocument",
    "CredentialsException",
    "Update",
    "Delete",
    "ReadConcern",
    "WriteConcern",
    "Collation",
    "Index",
    "User",
    "BuildInfo",
    "HelloResult",
    "SchemaGenerator",
    "Document",
    "Session",
    "Transaction",
    "xJsonT",
    "HasToDict",
    "chain",
    "filter_non_null",
    "maybe_to_dict"
]
