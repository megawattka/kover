"""Read existing data with client, cursor, and command routing policies."""

import asyncio
import logging
import os

from kover import (
    AuthCredentials,
    ReadPreference,
    ServerSelectionError,
    from_uri,
    make_client,
)

log = logging.getLogger(__name__)


async def main() -> None:
    """Demonstrate read routing and close every cursor and client."""
    uri = os.getenv("MONGODB_URI")
    if uri:  # dont forget about selection timeout
        log.info("Using uri: %s", uri)
        client = await from_uri(uri)
    else:
        client = await make_client(
            credentials=AuthCredentials.from_environ(),
            read_preference=ReadPreference(mode="secondaryPreferred"),
            server_selection_timeout=3.0,
        )

    async with client:
        database = client.get_database("db")
        collection = database.get_collection("items")

        # Without an override, the cursor inherits the client's policy.
        async with collection.find().limit(3) as cursor:
            log.info("Docs found: %s", await cursor.to_list())

        preferences = (
            ReadPreference(mode="primary"),
            ReadPreference(mode="primaryPreferred"),
            ReadPreference(mode="secondary"),
            ReadPreference(mode="secondaryPreferred"),
            ReadPreference(mode="nearest"),
            ReadPreference(
                mode="nearest",
                # Prefer matching tags; {} permits any eligible server.
                tag_sets=({"region": "eu"}, {}),
                max_staleness_seconds=120,
            ),
        )
        for preference in preferences:
            try:
                # Set the policy before starting iteration. getMore stays
                # on the server selected by the initial find command.
                async with (
                    collection.find().read_preference(preference).limit(3)
                ) as cursor:
                    documents = await cursor.to_list()
            except ServerSelectionError:
                log.warning("No eligible server for %s", preference.to_dict())
            else:
                log.info("%s: found: %s", preference.to_dict(), documents)

        # command() accepts an explicit policy too. Keep the command name
        # first; only supported read commands use non-primary routing.
        result = await client.command(
            {"count": collection.name, "query": {}},
            db_name=database.name,
            read_preference=ReadPreference(mode="primary"),
        )
        log.info("Documents found in primary: %s", result["n"])


if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO)
    asyncio.run(main())
