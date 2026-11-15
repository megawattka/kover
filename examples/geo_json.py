"""Store typed GeoJSON and find nearby cafes."""

import asyncio
import logging
import os
from uuid import uuid4

from kover import Document, Index, IndexType, from_uri
from kover.geo import Point, Polygon

log = logging.getLogger(__name__)


class Place(Document):
    """A named place with a validated WGS84 location."""

    name: str
    location: Point


async def main() -> None:
    """Create an index, validate documents, and query nearby places."""
    async with await from_uri(os.environ["MONGODB_URI"]) as client:
        database = client.get_database("kover_geo_example_" + uuid4().hex)
        try:
            places = await database.create_collection("places")
            schema = Place.model_mongodb_schema()
            await places.set_validator(schema)

            idx = Index(
                "location_2dsphere", {
                    "location": IndexType.GEO_2DSPHERE,
                },
            )
            await places.create_indexes(idx)

            center = Point.from_lon_lat(longitude=37.6173, latitude=55.7558)
            outskirts = Point.from_lon_lat(longitude=37.7, latitude=55.8)
            await places.insert_many([
                Place(name="Cafe nearby", location=center),
                Place(
                    name="Cafe further away",
                    location=outskirts,
                ),
            ])
            nearby = await places.find({
                "location": {
                    "$near": {
                        "$geometry": center.model_dump(),
                        "$maxDistance": 1000,
                    },
                },
            }, cls=Place).to_list()
            for place in nearby:
                log.info("Nearby: %s (%s)", place.name, place.location)

            area = Polygon(coordinates=[[
                (37.60, 55.74),
                (37.64, 55.74),
                (37.64, 55.77),
                (37.60, 55.77),
                (37.60, 55.74),
            ]])
            within = await places.find({
                "location": {
                    "$geoWithin": {
                        "$geometry": area.model_dump(),
                    },
                },
            }, cls=Place).to_list()
            log.info("Inside area: %s", [place.name for place in within])

            # Return nearby places ordered by distance and add the
            # calculated distance in meters to each result.
            distances = await places.aggregate([
                {
                    "$geoNear": {
                        "near": center.model_dump(),
                        "key": "location",
                        "distanceField": "distance_meters",
                        "spherical": True,
                        "maxDistance": 1000,
                    },
                },
            ]).to_list()

            for result in distances:
                log.info(
                    "%s: %.1f m", result["name"], result["distance_meters"],
                )
        finally:
            await client.drop_database(database.name)


if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO)
    asyncio.run(main())
