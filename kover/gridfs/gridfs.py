from __future__ import annotations

import datetime
import math
from pathlib import Path
from io import BytesIO
from typing import (
    Optional,
    Final,
    BinaryIO,
    TextIO,
    List
)
from hashlib import sha1

from bson import ObjectId

from ..models import Index
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

DEFAULT_CHUNK_SIZE: Final[int] = 255 * 1024


class GridFS:
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
        if isinstance(data, (str, TextIO, BinaryIO, Path)):
            if isinstance(data, TextIO):
                # StringIO (?)
                binary = BytesIO(
                    data.read().encode(encoding=encoding)
                )
            elif isinstance(data, str):
                path = Path(data)
                if path.exists():
                    # string as path
                    binary = BytesIO(path.read_bytes())
                    name = path.name
                else:
                    # str
                    binary = BytesIO(
                        data.encode(encoding=encoding)
                    )
            elif isinstance(data, BinaryIO):
                # BytesIO
                if data.tell() != 0:
                    data.seek(0)
                binary = BytesIO(data.read())
            else:
                # Path
                name = data.name
                binary = BytesIO(data.read_bytes())
        else:
            # bytes
            binary = BytesIO(data)
        return binary, name

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
        >>> fs = GridFS(database)
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
            chunks.append(Chunk(
                files_id=file_id,
                n=n,
                data=data
            ))
        await self._chunks.insert(chunks)
        upload_date = datetime.datetime.now()
        file = File(
            chunk_size=chunk_size,
            length=size,
            upload_date=upload_date,
            filename=filename,
            metadata={
                "sha1": sha1(binary.getvalue()).hexdigest()
            } if add_sha1 else {}
        ).id(file_id)
        file.metadata.update(metadata or {})
        await self._files.insert(file.to_dict(exclude_id=False))
        return file_id

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
                binary.write(chunk["data"])
            binary.seek(0)
            if check_sha1:
                stored_sha1 = file.metadata.get("sha1")
                if stored_sha1 is not None:
                    assert stored_sha1 == sha1(
                        binary.getvalue()
                    ).hexdigest(), "sha1 hash mismatch"
            return file, binary
        raise GridFSFileNotFound("No file with that id found")

    async def get_by_filename(self, filename: str) -> tuple[File, BytesIO]:
        file = await self._files.find_one({"filename": filename}, cls=File)
        if file is not None:
            return await self.get_by_file_id(file.id())
        raise GridFSFileNotFound("No file with that filename found")

    async def delete(self, file_id: ObjectId) -> bool:
        deleted = await self._files.delete_one({"_id": file_id})
        if deleted:
            await self._chunks.delete_many({"files_id": file_id})
        return deleted

    async def list(self) -> List[File]:
        return await self._files.find(cls=File).to_list()

    async def exists(self, file_id: ObjectId) -> bool:
        file = await self._files.find_one({"_id": file_id})
        return file is not None

    async def create_indexes(self) -> None:
        await self._chunks.create_indexes(CHUNKS_IDX)
        await self._files.create_indexes(FS_IDX)
