import asyncio  # noqa: D100
import json
import logging
import os
from pathlib import Path
import sys
import time
from typing import TYPE_CHECKING, Final

from motor.motor_tornado import MotorClient
from pymongo import AsyncMongoClient

sys.path.insert(0, ".")
from kover import Kover

if TYPE_CHECKING:
    from kover import xJsonT

log = logging.getLogger(__name__)
logging.basicConfig(level=logging.INFO)
asyncio.set_event_loop_policy(asyncio.WindowsSelectorEventLoopPolicy())

CONCURRENCIES: Final[list[int]] = [1, 2, 4, 8, 16, 32, 64, 96, 128, 160, 192, 256, 384, 512]  # noqa: E501
RESULTS_DIR = Path(__file__).parent / "results"
RESULTS_DIR.mkdir(exist_ok=True)


def _random_document() -> "xJsonT":
    return {
        "name": os.urandom(8).hex(),
        "age": int.from_bytes(os.urandom(2), "little"),
        "uuid": str(os.urandom(16).hex()),
    }


total: dict[str, list[float]] = {str(key): [] for key in CONCURRENCIES}


async def benchmark_kover() -> None:
    """Entrypoint."""
    client = await Kover.from_uri("mongodb://main_m1:incunaby!@127.0.0.1:27017?tls=false")

    database = client.get_database("benchmarks")
    collection = database.get_collection("benchmark")
    for _ in range(3):
        for concurrency in CONCURRENCIES:
            ts = time.time()
            log.info("Running benchmark with concurrency: %s", concurrency)
            tasks = [
                collection.insert_many([_random_document() for _ in range(1000)])  # noqa: E501
                for _ in range(concurrency)
            ]
            await asyncio.gather(*tasks)
            elapsed = time.time() - ts
            total[str(concurrency)].append(elapsed)
            log.info("%s ms", elapsed)

    log.info("Benchmark results: %s", total)
    with RESULTS_DIR.joinpath("kover.json").open("w", encoding="utf-8") as fp:
        json.dump({
            "benchmarks": [{
                "type": "insertMany",
                "library": "kover",
                "results": total,
            }],
        }, fp, indent=4)

    log.info("Clearing up...")
    cleared = await collection.clear()
    log.info("%d documents cleared from the collection.", cleared)
    await client.close()


async def benchmark_pymongo() -> None:
    """Entrypoint."""
    client: AsyncMongoClient[xJsonT] = AsyncMongoClient("mongodb://main_m1:incunaby!@127.0.0.1:27017?tls=false")

    database = client.get_database("benchmarks")
    collection = database.get_collection("benchmark")
    for _ in range(3):
        for concurrency in CONCURRENCIES:
            ts = time.time()
            log.info("Running benchmark with concurrency: %s", concurrency)
            tasks = [
                collection.insert_many([_random_document() for _ in range(1000)])  # noqa: E501
                for _ in range(concurrency)
            ]
            await asyncio.gather(*tasks)
            elapsed = time.time() - ts
            total[str(concurrency)].append(elapsed)
            log.info("%s ms", elapsed)

    log.info("Benchmark results: %s", total)
    with RESULTS_DIR.joinpath("pymongo.json").open("w", encoding="utf-8") as fp:  # noqa: E501
        json.dump({
            "benchmarks": [{
                "type": "insertMany",
                "library": "pymongo",
                "results": total,
            }],
        }, fp, indent=4)

    log.info("Clearing up...")
    cleared = await collection.drop()
    log.info("%s documents cleared from the collection.", cleared)
    await client.close()


async def benchmark_motor() -> None:
    """Entrypoint."""
    client: MotorClient[xJsonT] = MotorClient("mongodb://main_m1:incunaby!@127.0.0.1:27017?tls=false")

    database = client.get_database("benchmarks")
    collection = database.get_collection("benchmark")
    for _ in range(3):
        for concurrency in CONCURRENCIES:
            ts = time.time()
            log.info("Running benchmark with concurrency: %s", concurrency)
            tasks = [
                collection.insert_many([_random_document() for _ in range(1000)])  # noqa: E501
                for _ in range(concurrency)
            ]
            await asyncio.gather(*tasks)
            elapsed = time.time() - ts
            total[str(concurrency)].append(elapsed)
            log.info("%s ms", elapsed)

    log.info("Benchmark results: %s", total)
    with RESULTS_DIR.joinpath("motor.json").open("w", encoding="utf-8") as fp:
        json.dump({
            "benchmarks": [{
                "type": "insertMany",
                "library": "motor",
                "results": total,
            }],
        }, fp, indent=4)

    log.info("Clearing up...")
    await collection.drop()
    client.close()


if __name__ == "__main__":
    # you need to run separately each benchmark
    # and restart database server after each run
    # because of performance degradation (?maybe my pc just garbage)
    asyncio.run(benchmark_kover())
