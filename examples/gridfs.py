"""Example of using GridFS with Kover.

This example demonstrates streaming uploads and downloads with GridFS.
"""

import asyncio
import logging

from kover import AuthCredentials, make_client
from kover.gridfs import GridFS

log = logging.getLogger(__name__)
logging.basicConfig(level=logging.INFO)


async def main() -> None:
    """Upload, stream back, and delete a file."""
    credentials = AuthCredentials.from_environ()
    async with await make_client(credentials=credentials) as client:
        fs = await GridFS(client.get_database("files")).indexed()

        # alias for await fs.put(b"Hello world!", filename="hello.txt")
        async with fs.open_upload_stream("hello.txt") as upload:
            await upload.write(b"Hello ")
            await upload.write(b"World!")

        file, download = await fs.open_download_stream(
            upload.file_id, chunk_size=1024,
        )
        async with download:
            async for chunk in download:
                log.info("%s: %s", file.filename, chunk)

        deleted = await fs.delete(upload.file_id)
        log.info("File deleted: %s", deleted)


if __name__ == "__main__":
    asyncio.run(main())
