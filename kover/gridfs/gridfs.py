"""The kover's grids implementation."""

from __future__ import annotations

from contextlib import aclosing
from io import BytesIO
from pathlib import Path
from typing import TYPE_CHECKING, Any, Final, Self

from ..models import Delete, Index, IndexDirection
from .exceptions import GridFSFileNotFound
from .models import File
from .sources import read_blocks
from .stream import GridFSDownloadStream
from .upload import DEFAULT_CHUNK_SIZE, GridFSUploadStream

if TYPE_CHECKING:
    from elune import ObjectId

    from ..database import Database
    from .annotations import GridFSPayloadT

# pre-created index models
FS_IDX: Final[Index] = Index(
    "_fs_idx",
    {
        "filename": IndexDirection.ASCENDING,
        "uploadDate": IndexDirection.ASCENDING,
    },
)
CHUNKS_IDX: Final[Index] = Index(
    "_chunks_idx",
    {
        "files_id": IndexDirection.ASCENDING,
        "n": IndexDirection.ASCENDING,
    },
    unique=True,
)


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

    def open_upload_stream(
        self,
        filename: str | None = None,
        *,
        chunk_size: int | None = None,
        add_sha1: bool = True,
        metadata: dict[str, Any] | None = None,
    ) -> GridFSUploadStream:
        """Create a stream you can write to with ``await stream.write(data)``.

        Use ``async with`` or explicitly call ``await stream.close()`` to
        publish the file. Use ``await stream.abort()`` to discard it instead.

        Returns:
            A new asynchronous GridFS upload stream.
        """
        size = DEFAULT_CHUNK_SIZE if chunk_size is None else chunk_size
        return GridFSUploadStream(
            self._files,
            self._chunks,
            filename=filename,
            chunk_size=size,
            add_sha1=add_sha1,
            metadata=metadata,
        )

    async def put(  # ruff: ignore[too-many-arguments] -- Explicit upload and metadata options.
        self,
        data: GridFSPayloadT,
        *,
        filename: str | None = None,
        encoding: str = "utf-8",
        chunk_size: int | None = None,
        add_sha1: bool = True,
        metadata: dict[str, Any] | None = None,
    ) -> ObjectId:
        """Store a file in GridFS without buffering the complete payload.

        Seekable file objects are read from the start. Caller-owned files and
        async sources are not closed. Local file reads run in a worker thread.

        Parameters:
            data : Bytes, text, a path, a file, or an async iterable of bytes.
            filename : The name of the file, defaults to None.
            encoding : Encoding to use if data is a string,
                defaults to "utf-8".
            chunk_size : Positive chunk size in bytes, small enough to fit in
                a BSON insert command. Defaults to 255 KiB.
            add_sha1 : Whether to add a SHA1 hash to the
                file metadata, defaults to True.
            metadata : Additional metadata to store with the file.

        Returns:
            The ObjectId of the stored file.
        """
        if isinstance(data, Path) and not filename:
            filename = data.name

        async with self.open_upload_stream(
            filename,
            chunk_size=chunk_size,
            add_sha1=add_sha1,
            metadata=metadata,
        ) as stream, aclosing(read_blocks(data, encoding)) as blocks:
            async for block in blocks:
                await stream.write(block)

        return stream.file_id

    async def get_by_file_id(
        self,
        file_id: ObjectId | None,
        *,
        check_sha1: bool = True,
    ) -> tuple[File, BytesIO]:
        """Retrieve the whole file by ID (raises if the file is missing).

        Parameters:
            file_id : The unique identifier of the file to retrieve.
            check_sha1 : Whether to verify the SHA1 hash of the file data,
                defaults to True.

        Returns:
            The File object and its binary data.
        """
        file, stream = await self.open_download_stream(
            file_id, check_sha1=check_sha1,
        )
        return file, await self._buffer_download(stream)

    @staticmethod
    async def _buffer_download(stream: GridFSDownloadStream) -> BytesIO:
        binary = BytesIO()
        async with stream:
            async for chunk in stream:
                binary.write(chunk)

        binary.seek(0)
        return binary

    async def open_download_stream(
        self,
        file_id: ObjectId | None,
        *,
        check_sha1: bool = True,
        chunk_size: int | None = None,
    ) -> tuple[File, GridFSDownloadStream]:
        """Open a file for bounded-memory asynchronous chunked reading.

        Consume the returned stream with ``async for`` inside ``async with``
        to close its cursor even if reading stops early.

        With ``chunk_size=None``, yield the original stored chunks. Otherwise,
        yield blocks of the requested size in bytes, except the final block,
        which may be shorter. The stored chunks are not modified.

        Returns:
            The file metadata and a chunked download stream.

        Raises:
            GridFSFileNotFound: If no file with the given ID is found.
        """
        file = await self._files.find_one({"_id": file_id}, cls=File)
        if file is None:
            msg = "No file with that id found"
            raise GridFSFileNotFound(msg)

        return file, self._make_download_stream(
            file,
            check_sha1=check_sha1,
            chunk_size=chunk_size,
        )

    def _make_download_stream(
        self,
        file: File,
        *,
        check_sha1: bool,
        chunk_size: int | None = None,
    ) -> GridFSDownloadStream:
        """Create a chunk cursor for a stored GridFS file.

        Returns:
            A stream over the file's chunks.
        """
        cursor = self._chunks.aggregate(
            [
                {"$match": {"files_id": file.object_id}},
                {"$sort": {"n": 1}},
            ],
        )
        stored_sha1 = file.metadata.get("sha1")
        if not isinstance(stored_sha1, str):
            stored_sha1 = None

        return GridFSDownloadStream(
            cursor,
            stored_sha1,
            check_sha1=check_sha1,
            file=file,
            chunk_size=chunk_size,
        )

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
            return file, await self._buffer_download(
                self._make_download_stream(file, check_sha1=True),
            )

        msg = "No file with that filename found"
        raise GridFSFileNotFound(msg)

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
