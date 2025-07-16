"""Example of using GridFS with Kover.

This example demonstrates how to put, get, list, and delete
files using Kover's GridFS implementation.
"""

import asyncio
import logging

from kover import AuthCredentials, Kover
from kover.gridfs import GridFS

log = logging.getLogger(__name__)
logging.basicConfig(level=logging.INFO)


async def main() -> None:  # noqa: D103
    credentials = AuthCredentials.from_environ()
    kover = await Kover.make_client(credentials=credentials)

    database = kover.get_database("files")
    fs = await GridFS(database).indexed()

    # can be bytes, any type of IO str or path
    file_id = await fs.put(b"Hello World!")

    file, binary = await fs.get_by_file_id(file_id)
    log.info(file, binary.read())

    files = await fs.list()
    log.info(f"total files: {len(files)}")

    deleted = await fs.delete(file_id)
    log.info(f"is file deleted? {deleted}")


if __name__ == "__main__":
    asyncio.run(main())
