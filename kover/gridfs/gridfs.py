"""The kover's grids implementation."""

from __future__ import annotations

import datetime as dt
from hashlib import sha1
from io import BytesIO
import math
from pathlib import Path
from typing import TYPE_CHECKING, BinaryIO, Final, Self

from bson import Binary, ObjectId

from .. import Delete, Index
from ..enums import IndexDirection
from .exceptions import GridFSFileNotFound, IncorrectGridFSData
from .models import Chunk, File

if TYPE_CHECKING:
    from ..database import Database
    from ..typings import GridFSPayloadT, JsonT

# pre-created index models
FS_IDX: Final[Index] = Index("_fs_idx", {
    "filename": IndexDirection.ASCENDING,
    "uploadDate": IndexDirection.ASCENDING,
})
CHUNKS_IDX: Final[Index] = Index("_chunks_idx", {
    "files_id": IndexDirection.ASCENDING,
    "n": IndexDirection.ASCENDING,
}, unique=True)

DEFAULT_CHUNK_SIZE: Final[int] = 255 * 1024  # from pymongo
SIZE_LIMIT: Final[int] = 1 * 1024 * 1024 * 16  # 16MB


class GridFS:
    """Create new instance of GridFS class."""

    def __init__(
        self,
        database: Database,
        *,
        collection: str = "fs",
    ) -> None:
        self._collection = database.get_collection(collection)
        self._files = self._collection.files
        self._chunks = self._collection.chunks

    @staticmethod
    def _get_binary_io(
        data: GridFSPayloadT,
        *,
        encoding: str = "utf-8",
    ) -> tuple[BytesIO, str | None]:
        name = None

        if isinstance(data, BinaryIO):  # io-like obj
            if data.tell() != 0 and data.seekable():
                data.seek(0)
            data = data.read()

        if isinstance(data, str):
            binary = BytesIO(data.encode(encoding=encoding))

        elif isinstance(data, Path):
            name = data.name
            binary = BytesIO(data.read_bytes())

        elif isinstance(data, bytes):
            binary = BytesIO(data)

        else:
            cls = getattr(data, "__class__", None)
            raise IncorrectGridFSData(f"Incorrect data passed: {cls}, {data}")

        binary.seek(0)
        return binary, name

    async def _partial_write_chunks(
        self,
        chunks: list[Chunk],
        chunk_size: int,
    ) -> None:
        total_chunks = len(chunks)
        if total_chunks == 0:
            return

        max_amount = max(1, math.ceil(SIZE_LIMIT / chunk_size) - 1)
        splitted = [
            chunks[x:x + max_amount]
            for x in range(0, len(chunks), max_amount)
        ]
        for chunk_group in splitted:
            await self._chunks.insert_many(chunk_group)

    async def put(
        self,
        data: GridFSPayloadT,
        *,
        filename: str | None = None,
        encoding: str = "utf-8",
        chunk_size: int | None = None,
        add_sha1: bool = True,
        metadata: JsonT | None = None,
    ) -> ObjectId:
        """Store a file in GridFS, splitting it into chunks.

        Parameters:
            data : The file data to store
                (can be bytes, str, Path, or file-like object).
            filename : The name of the file, defaults to None.
            encoding : Encoding to use if data is a string,
                defaults to "utf-8".
            chunk_size : Size of each chunk in bytes,
                defaults to DEFAULT_CHUNK_SIZE.
            add_sha1 : Whether to add a SHA1 hash to the
                file metadata, defaults to True.
            metadata : Additional metadata to store with the file.

        Returns:
            The ObjectId of the stored file.

        Raises:
            ValueError: if ``chunk_size`` is not positive or exceeds the
                maximum BSON document size.
        """
        chunk_size = DEFAULT_CHUNK_SIZE if chunk_size is None else chunk_size
        if isinstance(chunk_size, bool) or not 0 < chunk_size < SIZE_LIMIT:
            raise ValueError(
                f"chunk_size must be > 0 and < {SIZE_LIMIT}",
            )
        file_id = ObjectId()

        binary, name = self._get_binary_io(data, encoding=encoding)
        chunks: list[Chunk] = []
        size = len(binary.getvalue())

        iterations = math.ceil(size / chunk_size)
        filename = filename or name

        for n in range(iterations):
            data = binary.read(chunk_size)
            chunk = Chunk(
                files_id=file_id,
                n=n,
                data=Binary(data),
            )
            chunks.append(chunk)
        await self._partial_write_chunks(
            chunks,
            chunk_size=chunk_size,
        )
        upload_date = dt.datetime.now(tz=dt.UTC)

        file = File(
            chunk_size=chunk_size,
            length=size,
            upload_date=upload_date,
            filename=filename,
            metadata={
                "sha1": sha1(binary.getvalue()).hexdigest(),
            } if add_sha1 else {},
        )
        file.set_object_id(file_id)

        file.metadata.update(metadata or {})
        await self._files.insert_one(
            file.to_dict(exclude_id=False),
        )
        return file_id

    async def get_by_file_id(
        self,
        file_id: ObjectId | None,
        *,
        check_sha1: bool = True,
    ) -> tuple[File, BytesIO]:
        """Retrieve a file and its binary data from GridFS by file ID.

        Parameters:
            file_id : The unique identifier of the file to retrieve.
            check_sha1 : Whether to verify the SHA1 hash of the file data,
                defaults to True.

        Returns:
            The File object and its binary data.

        Raises:
            GridFSFileNotFound : If no file with the given ID is found.
        """
        file = await self._files.find_one({"_id": file_id}, cls=File)
        if file is not None:
            chunks = await self._chunks.aggregate([
                {"$match": {"files_id": file_id}},
                {"$sort": {"n": 1}},
            ]).to_list()
            binary = BytesIO()
            for chunk in chunks:
                binary.write(chunk["data"])
            binary.seek(0)
            if check_sha1:
                stored_sha1 = file.metadata.get("sha1")
                if stored_sha1 is not None:
                    assert stored_sha1 == sha1(
                        binary.getvalue(),
                    ).hexdigest(), "sha1 hash mismatch"
            return file, binary
        raise GridFSFileNotFound("No file with that id found")

    async def get_by_filename(
        self,
        filename: str,
    ) -> tuple[File, BytesIO]:
        """Retrieve a file and its binary data from GridFS by filename.

        Parameters:
            filename : The name of the file to retrieve.

        Returns:
            The File object and its binary data.

        Raises:
            GridFSFileNotFound : If no file with the given filename is found.
        """
        file = await self._files.find_one({"filename": filename}, cls=File)
        if file is not None:
            document_id = file.get_object_id()
            return await self.get_by_file_id(document_id)

        raise GridFSFileNotFound("No file with that filename found")

    async def delete(
        self,
        file_id: ObjectId,
    ) -> bool:
        """Delete a file and its associated chunks from GridFS by file ID.

        Parameters:
            file_id : The unique identifier of the file to delete.

        Returns:
            True if the file was deleted, False otherwise.
        """
        deleted = await self._files.delete(Delete({"_id": file_id}, limit=1))
        if deleted:
            await self._chunks.delete(Delete({"files_id": file_id}, limit=0))
        return bool(deleted)

    async def drop_all_files(self) -> int:
        """Delete all files and their associated chunks from GridFS.

        Returns:
            The number of files deleted.
        """
        await self._chunks.clear()
        return await self._files.clear()

    async def list(self) -> list[File]:
        """List all files stored in GridFS.

        Returns:
            List of "File" objects, stored in GridFS.
        """
        cursor = self._files.find(cls=File)
        return await cursor.to_list()

    async def exists(
        self,
        file_id: ObjectId,
    ) -> bool:
        """Check if a file exists in GridFS by its ObjectId.

        Parameters:
            file_id : The unique identifier of the file to check.

        Returns:
            True if the file exists, False otherwise.
        """
        file = await self._files.find_one({"_id": file_id})
        return file is not None

    async def indexed(self) -> Self:
        """Create necessary indexes for GridFS files and chunks collections.

        Returns:
            The GridFS instance with ensured indexes.
        """
        await self._chunks.create_indexes(CHUNKS_IDX)
        await self._files.create_indexes(FS_IDX)
        return self
