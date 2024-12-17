import time
import asyncio
import os

import pymongo
from gridfs import (
    AsyncGridFS as PymongoAsyncGridFS,
    GridFS as PymongoGridFS
)
from kover.gridfs import GridFS as KoverGridFS
from kover.auth import AuthCredentials
from kover.client import Kover

DATA = {
    1: 100,  # 100mb 1 time
    10: 10,  # 10mb 10 times
    100: 1  # 1mb 100 times
}


async def bench_kover_gridfs() -> None:
    print("TESTING KOVER")
    credentials = AuthCredentials.from_environ()
    client = await Kover.make_client(credentials=credentials)
    database = client.get_database("test1")
    fs = await KoverGridFS(database).indexed()
    for times, amount in DATA.items():
        ts = time.time()
        for _ in range(times):
            await fs.put(os.urandom(1 * 1024 * 1024 * amount))
        print(time.time() - ts, f"{amount}MB x {times} times")
    await fs.drop_all_files()


def bench_pymongo_sync_gridfs() -> None:
    print("TESTING PYMONGO SYNC")
    client = pymongo.MongoClient(  # type: ignore
        username="main_m1",
        password="incunaby!"
    )
    database = client.get_database("test1")  # type: ignore
    fs = PymongoGridFS(database)
    for times, amount in DATA.items():
        ts = time.time()
        for _ in range(times):
            fs.put(os.urandom(1 * 1024 * 1024 * amount))
        print(time.time() - ts, f"{amount}MB x {times} times")
    fs._chunks.delete_many({})  # type: ignore
    fs._files.delete_many({})  # type: ignore


async def bench_pymongo_async_gridfs() -> None:
    print("TESTING PYMONGO ASYNC")
    client = pymongo.AsyncMongoClient(  # type: ignore
        username="main_m1",
        password="incunaby!"
    )
    database = client.get_database("test1")  # type: ignore
    fs = PymongoAsyncGridFS(database)
    for times, amount in DATA.items():
        ts = time.time()
        for _ in range(times):
            await fs.put(os.urandom(1 * 1024 * 1024 * amount))
        print(time.time() - ts, f"{amount}MB x {times} times")
    await fs._chunks.delete_many({})  # type: ignore
    await fs._files.delete_many({})  # type: ignore


async def main() -> None:
    # this not depends on the libs much.
    # idk why i created this bench
    # because its totally testing system write speed
    # and can give totally random results due to lags
    # https://files.catbox.moe/8pxt73.png
    # https://files.catbox.moe/zgdxtg.png
    await bench_kover_gridfs()
    bench_pymongo_sync_gridfs()
    await bench_pymongo_async_gridfs()

if __name__ == "__main__":
    asyncio.run(main())
