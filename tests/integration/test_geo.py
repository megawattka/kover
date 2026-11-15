import pytest

from kover import Document, Index, IndexType, OperationFailure
from kover.geo import Geometry, GeometryCollection, Point, Polygon  # ruff: ignore[typing-only-first-party-import] -- Pydantic resolves model annotations at runtime.
from tests.integration.base import MongoTestCase


class Place(Document):
    name: str
    location: Point


class GeoIntegrationTests(MongoTestCase):
    async def test_all_geometry_types_can_be_indexed_and_loaded(self) -> None:
        class Shape(Document):
            geometry: Geometry

        shapes = await self.database.create_collection("shapes")
        await shapes.create_indexes(
            Index("geo", {"geometry": IndexType.GEO_2DSPHERE}),
        )
        ring = [[0, 0], [1, 0], [1, 1], [0, 1], [0, 0]]
        payloads = [
            {"type": "Point", "coordinates": [0, 0]},
            {"type": "LineString", "coordinates": [[0, 0], [1, 1]]},
            {"type": "Polygon", "coordinates": [ring]},
            {"type": "MultiPoint", "coordinates": [[0, 0], [1, 1]]},
            {"type": "MultiLineString", "coordinates": [[[0, 0], [1, 1]]]},
            {"type": "MultiPolygon", "coordinates": [[ring]]},
        ]
        for payload in payloads:
            original = Shape.model_validate({"geometry": payload})
            identifier = await shapes.insert_one(original)
            loaded = await shapes.find_one({"_id": identifier}, cls=Shape)
            assert loaded is not None
            assert loaded.geometry == original.geometry
        collection = Shape(geometry=GeometryCollection(geometries=[
            Point(coordinates=(0, 0)),
        ]))
        identifier = await shapes.insert_one(collection)
        loaded = await shapes.find_one({"_id": identifier}, cls=Shape)
        assert loaded is not None
        assert loaded.geometry == collection.geometry

    async def test_schema_index_roundtrip_and_queries(self) -> None:
        places = await self.database.create_collection("places")
        await places.set_validator(Place.model_mongodb_schema())
        await places.create_indexes(
            Index("location_2dsphere", {"location": IndexType.GEO_2DSPHERE}),
        )
        indexes = await places.list_indexes()
        assert any(
            index.key == {"location": "2dsphere"}
            for index in indexes
        )
        origin = Point.from_lon_lat(longitude=0, latitude=0)
        await places.insert_many([
            Place(name="near", location=origin),
            Place(name="middle", location=Point(coordinates=(0.005, 0))),
            Place(name="far", location=Point(coordinates=(10, 10))),
        ])
        for operator in ("$near", "$nearSphere"):
            nearby = await places.find({
                "location": {operator: {
                    "$geometry": origin.model_dump(), "$maxDistance": 1000,
                }},
            }, cls=Place).to_list()
            assert [place.name for place in nearby] == ["near", "middle"]
            assert nearby[0].location == origin
            annulus = await places.find({
                "location": {operator: {
                    "$geometry": origin.model_dump(),
                    "$minDistance": 100,
                    "$maxDistance": 1000,
                }},
            }, cls=Place).to_list()
            assert [place.name for place in annulus] == ["middle"]
        area = Polygon(coordinates=[[
            (-1, -1), (1, -1), (1, 1), (-1, 1), (-1, -1),
        ]])
        for operator in ("$geoWithin", "$geoIntersects"):
            found = await places.find({
                "location": {operator: {"$geometry": area.model_dump()}},
            }, cls=Place).to_list()
            assert {place.name for place in found} == {"near", "middle"}
        distances = await places.aggregate([{"$geoNear": {
            "near": origin.model_dump(),
            "key": "location",
            "distanceField": "distance",
            "spherical": True,
            "maxDistance": 1000,
        }}]).to_list()
        assert [place["name"] for place in distances] == ["near", "middle"]
        assert distances[0]["distance"] == pytest.approx(0)
        assert distances[1]["distance"] == pytest.approx(556.6, rel=0.01)

        with pytest.raises(OperationFailure) as caught:
            await places.insert_one({
                "name": "invalid", "location": {"coordinates": [0.0, 0.0]},
            })
        assert caught.value.code == 121

    async def test_polygon_topology_is_checked_by_mongodb(self) -> None:
        regions = await self.database.create_collection("regions")
        await regions.create_indexes(
            Index("shape_2dsphere", {"shape": IndexType.GEO_2DSPHERE}),
        )
        payloads = [
            # Structurally closed, but self-intersecting on the sphere.
            [[(0, 0), (2, 2), (0, 2), (2, 0), (0, 0)]],
            # Interior ring outside the exterior ring.
            [
                [(0, 0), (4, 0), (4, 4), (0, 4), (0, 0)],
                [(5, 5), (5, 6), (6, 6), (6, 5), (5, 5)],
            ],
            # Two intersecting interior rings.
            [
                [(0, 0), (8, 0), (8, 8), (0, 8), (0, 0)],
                [(1, 1), (1, 4), (4, 4), (4, 1), (1, 1)],
                [(3, 3), (3, 6), (6, 6), (6, 3), (3, 3)],
            ],
        ]
        for coordinates in payloads:
            polygon = Polygon.model_validate({"coordinates": coordinates})
            with pytest.raises(OperationFailure):
                await regions.insert_one({"shape": polygon.model_dump()})
        assert await regions.count() == 0

    async def test_polygon_with_hole_excludes_hole_from_queries(self) -> None:
        class Region(Document):
            shape: Polygon

        polygon = Polygon(coordinates=[
            [(-4, -4), (4, -4), (4, 4), (-4, 4), (-4, -4)],
            [(-1, -1), (-1, 1), (1, 1), (1, -1), (-1, -1)],
        ])
        regions = await self.database.create_collection("regions")
        await regions.set_validator(Region.model_mongodb_schema())
        await regions.create_indexes(
            Index("shape_geo", {"shape": IndexType.GEO_2DSPHERE}),
        )
        identifier = await regions.insert_one(Region(shape=polygon))
        loaded = await regions.find_one({"_id": identifier}, cls=Region)
        assert loaded is not None
        assert loaded.shape == polygon

        points = await self.database.create_collection("points")
        await points.create_indexes(
            Index("point_geo", {"location": IndexType.GEO_2DSPHERE}),
        )
        await points.insert_many([
            Place(name="shell", location=Point(coordinates=(2, 0))),
            Place(name="hole", location=Point(coordinates=(0, 0))),
            Place(name="outside", location=Point(coordinates=(10, 0))),
        ])
        for operator in ("$geoWithin", "$geoIntersects"):
            found = await points.find({
                "location": {operator: {"$geometry": polygon.model_dump()}},
            }, cls=Place).to_list()
            assert [place.name for place in found] == ["shell"]

        for coordinates, expected in [((2, 0), 1), ((0, 0), 0), ((10, 0), 0)]:
            intersecting = await regions.find({
                "shape": {"$geoIntersects": {"$geometry": Point(
                    coordinates=coordinates,
                ).model_dump()}},
            }).to_list()
            assert len(intersecting) == expected

    async def test_legacy_2d_index_roundtrip(self) -> None:
        points = await self.database.create_collection("legacy_points")
        await points.create_indexes(
            Index("location_2d", {"location": IndexType.GEO_2D}),
        )
        assert any(
            index.key == {"location": "2d"}
            for index in await points.list_indexes()
        )
        await points.insert_many([
            {"name": "near", "location": [0, 0]},
            {"name": "far", "location": [10, 10]},
        ])
        found = await points.find({
            "location": {"$near": [0, 0], "$maxDistance": 1},
        }).to_list()
        assert [point["name"] for point in found] == ["near"]
