"""Example of using Bulk Writes with Kover."""
from __future__ import annotations

import asyncio
import logging
from typing import TYPE_CHECKING

from kover import AuthCredentials, BulkWriteBuilder, Delete, Kover, Update

if TYPE_CHECKING:
    from kover.typings import JsonT

log = logging.getLogger(__name__)
logging.basicConfig(level=logging.INFO)


async def main() -> None:
    """Entrypoint."""
    credentials = AuthCredentials.from_environ()
    client = await Kover.make_client(credentials=credentials)

    builder = BulkWriteBuilder()
    builder.add_insert([{"foo": "bar"}], ns="test.foos")
    builder.add_update(
        Update({"foo": "bar"}, {"$set": {"foo": "baz"}}),
        ns="test.foos",
    )
    builder.add_delete(Delete({"foo": "baz"}, limit=1), ns="test.foos")
    # here we are inserting document
    # updating it instantly
    # and instantly deleting.
    # all operations being done step by step

    # see result output by bulk write
    results: list[JsonT] = await client.bulk_write(builder.build()).to_list()
    log.info(results)

    docs = await client.test.foos.find().to_list()
    log.info(docs)  # no docs found


if __name__ == "__main__":
    asyncio.run(main())
