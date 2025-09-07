"""Example of using Bulk Writes with Kover."""

import asyncio
import logging

from kover import (
    BulkWriteBuilder,
    Delete,
    Kover,
    Update,
)

log = logging.getLogger(__name__)
logging.basicConfig(level=logging.INFO)


async def main() -> None:
    """Entrypoint."""
    client = await Kover.from_uri("mongodb://127.0.0.1:27017?tls=false")

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

    await client.bulk_write(builder.build())

    docs = await client.test.foos.find().to_list()
    log.info(docs)  # no docs found


if __name__ == "__main__":
    asyncio.run(main())
