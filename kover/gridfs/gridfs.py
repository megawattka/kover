from __future__ import annotations

import datetime
import math
from pathlib import Path
from io import BytesIO
from typing import (
    Optional,
    Final,
    List
)
from hashlib import sha1

from bson import ObjectId
from typing_extensions import Self

from ..models import Index, Delete
from ..database import Database
from ..enums import IndexDirection
from ..typings import GridFSPayloadT, xJsonT
from .models import Chunk, File
from .exceptions import GridFSFileNotFound

# pre-created index models
FS_IDX: Final[Index] = Index("_fs_idx", {
    "filename": IndexDirection.ASCENDING,
    "uploadDate": IndexDirection.ASCENDING
})
CHUNKS_IDX: Final[Index] = Index("_chunks_idx", {
    "files_id": IndexDirection.ASCENDING,
    "n": IndexDirection.ASCENDING
}, unique=True)

DEFAULT_CHUNK_SIZE: Final[int] = 255 * 1024  # from pymongo
SIZE_LIMIT: Final[int] = 1 * 1024 * 1024 * 16  # 16MB


class GridFS:
    """
    create new instance of GridFS class.
    """
    def __init__(
        self,
        database: Database,
        *,
        collection: str = "fs"
    ) -> None:
        self._collection = database.get_collection(collection)
        self._files = self._collection.files
        self._chunks = self._collection.chunks

    def _get_binary_io(
        self,
        data: GridFSPayloadT,
        *,
        encoding: str = "utf-8"
    ) -> tuple[BytesIO, Optional[str]]:
        name = None
        if hasattr(data, "read"):  # io-like obj
            if data.tell() != 0 and data.seekable():  # type: ignore
                data.seek(0)  # type: ignore
            data = data.read()  # type: ignore
        if isinstance(data, str):
            binary = BytesIO(
                data.encode(encoding=encoding)
            )
        elif isinstance(data, Path):
            name = data.name
            binary = BytesIO(data.read_bytes())
        elif isinstance(data, bytes):
            binary = BytesIO(data)
        else:
            cls = getattr(data, "__class__")  # type: ignore
            raise Exception(
                f"Incorrect data passed: {cls}, {data}"
            )
        binary.seek(0)
        return binary, name

    async def _partial_write_chunks(
        self,
        chunks: List[Chunk],
        chunk_size: int
    ) -> None:
        total_chunks = len(chunks)
        max_amount = math.ceil(
            total_chunks / (
                total_chunks * chunk_size / SIZE_LIMIT
            )
        ) - 1
        splitted = [
            chunks[x:x+max_amount]
            for x in range(0, len(chunks), max_amount)
        ]
        for chunk_group in splitted:
            await self._chunks.insert(chunk_group)

    async def put(
        self,
        data: GridFSPayloadT,
        *,
        filename: Optional[str] = None,
        encoding: str = "utf-8",
        chunk_size: Optional[int] = None,
        add_sha1: bool = True,
        metadata: Optional[xJsonT] = None
    ) -> ObjectId:
        """
        divide data into chunks and store them into gridfs
        also auto adds sha1 hash if add_sha1 param is True
        >>> database = kover.get_database("files")
        >>> fs = await GridFS(database).indexed()
        >>> file_id = await fs.put("<AnyIO or bytes or str or path..>")
        >>> file, binary = await fs.get_by_file_id(file_id)
        >>> print(file, binary.read())
        >>> files = await fs.list_files()
        >>> print(files)
        """
        chunk_size = chunk_size or DEFAULT_CHUNK_SIZE
        file_id = ObjectId()

        binary, name = self._get_binary_io(data, encoding=encoding)
        chunks: List[Chunk] = []
        size = len(binary.getvalue())

        iterations = math.ceil(
            size / chunk_size
        )
        filename = filename or name

        for n in range(iterations):
            data = binary.read(chunk_size)
            chunk = Chunk(
                files_id=file_id,
                n=n,
                data=data
            )
            chunks.append(chunk)

        await self._partial_write_chunks(
            chunks,
            chunk_size=chunk_size
        )
        upload_date = datetime.datetime.now()

        file = File(
            chunk_size=chunk_size,
            length=size,
            upload_date=upload_date,
            filename=filename,
            metadata={
                "sha1": sha1(binary.getvalue()).hexdigest()
            } if add_sha1 else {}
        ).id(file_id)  # setting id to predefined

        file.metadata.update(metadata or {})
        return await self._files.insert(
            file.to_dict(exclude_id=False)
        )

    async def get_by_file_id(
        self,
        file_id: ObjectId,
        check_sha1: bool = True
    ) -> tuple[File, BytesIO]:
        file = await self._files.find_one({"_id": file_id}, cls=File)
        if file is not None:
            chunks = await self._chunks.aggregate([
                {"$match": {"files_id": file_id}},
                {"$sort": {"n": 1}}
            ])
            binary = BytesIO()
            for chunk in chunks:
                binary.write(chunk.pop("data"))
            binary.seek(0)
            if check_sha1:
                stored_sha1 = file.metadata.get("sha1")
                if stored_sha1 is not None:
                    assert stored_sha1 == sha1(
                        binary.getvalue()
                    ).hexdigest(), "sha1 hash mismatch"
            return file, binary
        raise GridFSFileNotFound("No file with that id found")

    async def get_by_filename(
        self,
        filename: str
    ) -> tuple[File, BytesIO]:
        file = await self._files.find_one({"filename": filename}, cls=File)
        if file is not None:
            return await self.get_by_file_id(file.id())
        raise GridFSFileNotFound("No file with that filename found")

    async def delete(
        self,
        file_id: ObjectId
    ) -> bool:
        deleted = await self._files.delete(Delete({"_id": file_id}, limit=1))
        if deleted:
            await self._chunks.delete(Delete({"files_id": file_id}, limit=0))
        return bool(deleted)

    async def drop_all_files(
        self,
    ) -> int:
        delete = Delete({}, limit=0)
        await self._chunks.delete(delete)
        deleted = await self._files.delete(delete)
        return deleted

    async def list(self) -> List[File]:
        return await self._files.find(cls=File).to_list()

    async def exists(
        self,
        file_id: ObjectId
    ) -> bool:
        file = await self._files.find_one({"_id": file_id})
        return file is not None

    async def indexed(self) -> Self:
        """return itself but creating indexes first"""
        await self._chunks.create_indexes(CHUNKS_IDX)
        await self._files.create_indexes(FS_IDX)
        return self
