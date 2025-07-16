"""Benchmarking script for Kover GridFS and PyMongo GridFS implementations."""

import asyncio
import logging
import os
import time

from gridfs import AsyncGridFS as PymongoAsyncGridFS
from gridfs import GridFS as PymongoGridFS
import pymongo

from kover.auth import AuthCredentials
from kover.client import Kover
from kover.gridfs import GridFS as KoverGridFS

DATA = {
    1: 100,  # 100mb 1 time
    10: 10,  # 10mb 10 times
    100: 1,  # 1mb 100 times
}
log = logging.getLogger("kover.benchmarks.gridfs")


async def bench_kover_gridfs() -> None:
    """Benchmark Kover GridFS."""
    log.info("TESTING KOVER GRIDFS")
    credentials = AuthCredentials.from_environ()
    client = await Kover.make_client(credentials=credentials)
    database = client.get_database("test1")
    fs = await KoverGridFS(database).indexed()
    for times, amount in DATA.items():
        ts = time.time()
        for _ in range(times):
            await fs.put(os.urandom(1 * 1024 * 1024 * amount))
        log.info(time.time() - ts, f"{amount}MB x {times} times")
    await fs.drop_all_files()


def bench_pymongo_sync_gridfs() -> None:
    """Benchmark Pymongo Sync GridFS."""
    log.info("TESTING PYMONGO SYNC GRIDFS")
    client = pymongo.MongoClient(  # type: ignore
        username="main_m1",
        password="incunaby!",  # noqa: S106
    )
    database = client.get_database("test1")  # type: ignore
    fs = PymongoGridFS(database)
    for times, amount in DATA.items():
        ts = time.time()
        for _ in range(times):
            fs.put(os.urandom(1 * 1024 * 1024 * amount))
        log.info(time.time() - ts, f"{amount}MB x {times} times")
    fs._chunks.delete_many({})  # type: ignore  # noqa: SLF001
    fs._files.delete_many({})  # type: ignore  # noqa: SLF001


async def bench_pymongo_async_gridfs() -> None:
    """Benchmark Pymongo Async GridFS."""
    log.info("TESTING PYMONGO ASYNC GRIDFS")
    client = pymongo.AsyncMongoClient(  # type: ignore
        username="main_m1",
        password="incunaby!",  # noqa: S106
    )
    database = client.get_database("test1")  # type: ignore
    fs = PymongoAsyncGridFS(database)
    for times, amount in DATA.items():
        ts = time.time()
        for _ in range(times):
            await fs.put(os.urandom(1 * 1024 * 1024 * amount))
        log.info(time.time() - ts, f"{amount}MB x {times} times")
    await fs._chunks.delete_many({})  # type: ignore  # noqa: SLF001
    await fs._files.delete_many({})  # type: ignore  # noqa: SLF001


async def main() -> None:
    """Gridfs benchmarks.

    This not depend on libs much.
    its just testing system write speed
    and can give totally random results due to system lags
    https://files.catbox.moe/8pxt73.png
    https://files.catbox.moe/zgdxtg.png.
    """
    await bench_kover_gridfs()
    bench_pymongo_sync_gridfs()
    await bench_pymongo_async_gridfs()


if __name__ == "__main__":
    asyncio.run(main())
