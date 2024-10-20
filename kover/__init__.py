# MIT License

# Copyright (c) 2024 oMegaPB

# Permission is hereby granted, free of charge, to any person obtaining a copy
# of this software and associated documentation files (the "Software"), to deal
# in the Software without restriction, including without limitation the rights
# to use, copy, modify, merge, publish, distribute, sublicense, and/or sell
# copies of the Software, and to permit persons to whom the Software is
# furnished to do so, subject to the following conditions:

# The above copyright notice and this permission notice shall be included in all
# copies or substantial portions of the Software.

# THE SOFTWARE IS PROVIDED "AS IS", WITHOUT WARRANTY OF ANY KIND, EXPRESS OR
# IMPLIED, INCLUDING BUT NOT LIMITED TO THE WARRANTIES OF MERCHANTABILITY,
# FITNESS FOR A PARTICULAR PURPOSE AND NONINFRINGEMENT. IN NO EVENT SHALL THE
# AUTHORS OR COPYRIGHT HOLDERS BE LIABLE FOR ANY CLAIM, DAMAGES OR OTHER
# LIABILITY, WHETHER IN AN ACTION OF CONTRACT, TORT OR OTHERWISE, ARISING FROM,
# OUT OF OR IN CONNECTION WITH THE SOFTWARE OR THE USE OR OTHER DEALINGS IN THE
# SOFTWARE.
try:
    import uvloop
except ModuleNotFoundError:
    pass
else:
    uvloop.install()

from .auth import AuthCredentials, Auth
from .collection import Collection
from .cursor import Cursor
from .models import Response
from .kover import MongoSocket, Kover
from .typings import xJsonT
from .session import Session, Transaction
from .socket import MongoSocket
from .serializer import Serializer
from .database import Database
from .schema import SchemaGenerator, TYPE_MAP, Document
from .exceptions import ValidationFailed
from .typings import xJsonT

__version__ = "0.3.2"
__author__ = "oMegaPB"
__license__ = "MIT"
__copyright__ = "Copyright (C) 2024-present oMegaPB <https://github.com/oMegaPB>"