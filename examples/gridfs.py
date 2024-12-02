import asyncio

from kover.client import Kover
from kover.gridfs import GridFS
from kover.auth import AuthCredentials


async def main():
    credentials = AuthCredentials.from_environ()
    kover = await Kover.make_client(credentials=credentials)

    database = kover.get_database("files")
    fs = GridFS(database)
    await fs.create_indexes()  # optional make fs collections indexed

    # can be bytes, any type of IO str or path
    file_id = await fs.put(b"Hello World!")

    file, binary = await fs.get_by_file_id(file_id)
    print(file, binary.read())

    files = await fs.list()
    print(f"total files: {len(files)}")

    deleted = await fs.delete(file_id)
    print("is file deleted?", deleted)

if __name__ == "__main__":
    asyncio.run(main())
