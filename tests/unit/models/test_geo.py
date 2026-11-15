from __future__ import annotations

from typing import TYPE_CHECKING, Any

from elune import decode, encode
from pydantic import TypeAdapter, ValidationError
import pytest

from kover import Document, Index, IndexType
from kover.exceptions import SchemaGenerationException
from kover.geo import (
    Geometry,
    GeometryCollection,
    LineString,
    MultiLineString,
    MultiPoint,
    MultiPolygon,
    Point,
    Polygon,
    StrictWindingCRS,
)
from kover.schema import MongoDBSchemaGenerator

if TYPE_CHECKING:
    from kover.geo import Position

RING: list[Position] = [(0.0, 0.0), (3.0, 6.0), (6.0, 1.0), (0.0, 0.0)]
GEOMETRIES = [
    Point(coordinates=(40, 5)),
    LineString(coordinates=[(40, 5), (41, 6)]),
    Polygon(coordinates=[RING]),
    MultiPoint(coordinates=[(40, 5), (41, 6)]),
    MultiLineString(coordinates=[[(40, 5), (41, 6)]]),
    MultiPolygon(coordinates=[[RING]]),
    GeometryCollection(geometries=[Point(coordinates=(40, 5))]),
]


class Place(Document):
    name: str
    location: Point


@pytest.mark.parametrize("altitude", [None, 0.0, -12.5, 150.0])
def test_named_point_constructor_and_properties(
    altitude: float | None,
) -> None:
    point = Point.from_lon_lat(
        longitude=37.6173, latitude=55.7558, altitude=altitude,
    )
    expected = (
        (37.6173, 55.7558)
        if altitude is None else (37.6173, 55.7558, altitude)
    )
    assert point.coordinates == expected
    assert point.longitude == pytest.approx(37.6173)
    assert point.latitude == pytest.approx(55.7558)
    assert point.altitude == altitude
    assert point == Point(coordinates=expected)
    assert set(point.model_dump()) == {"type", "coordinates"}


@pytest.mark.parametrize(
    ("longitude", "latitude", "altitude"),
    [
        (181, 0, None), (0, 91, None), (True, 0, None),
        (float("nan"), 0, None), (0, float("inf"), None),
        (0, 0, float("inf")), (0, 0, True),
    ],
)
def test_named_point_constructor_validates_coordinates(
    longitude: float, latitude: float, altitude: float | None,
) -> None:
    with pytest.raises(ValidationError):
        Point.from_lon_lat(
            longitude=longitude, latitude=latitude, altitude=altitude,
        )


def test_point_properties_follow_coordinate_assignment() -> None:
    point = Point.from_lon_lat(longitude=0, latitude=0)
    point.coordinates = (12, 34, 56)
    assert (point.longitude, point.latitude, point.altitude) == (12, 34, 56)
    point.coordinates = (-12, -34)
    assert (point.longitude, point.latitude, point.altitude) == (
        -12, -34, None,
    )


def test_named_point_constructor_preserves_subclass() -> None:
    class NamedPoint(Point):
        name: str = "origin"

    point = NamedPoint.from_lon_lat(longitude=0, latitude=0)
    assert isinstance(point, NamedPoint)


@pytest.mark.parametrize("geometry", GEOMETRIES)
def test_geometry_json_bson_roundtrip(geometry: Geometry) -> None:
    adapter = TypeAdapter(Geometry)
    payload = geometry.model_dump(mode="json")
    assert payload["type"] == type(geometry).__name__
    assert "_id" not in payload
    assert "crs" not in payload
    assert adapter.validate_json(geometry.model_dump_json()) == geometry
    bson = decode(encode({"geometry": geometry.model_dump()}))
    assert bson["geometry"] == payload
    assert adapter.validate_python(bson["geometry"]) == geometry


@pytest.mark.parametrize(
    "coordinates",
    [(-180, -90), (180, 90), (0, 0, -12.5)],
)
def test_position_boundaries_and_altitude(
    coordinates: tuple[float, float] | tuple[float, float, float],
) -> None:
    assert Point(coordinates=coordinates).coordinates == coordinates


@pytest.mark.parametrize(
    "coordinates",
    [
        [], [1], [0, 0, 0, 0], [181, 0], [-181, 0], [0, 91],
        [0, -91], [True, 0], ["1", 0], [None, 0],
        [float("nan"), 0], [0, float("inf")], [0, 0, float("-inf")],
    ],
)
def test_invalid_positions(coordinates: list[object]) -> None:
    with pytest.raises(ValidationError):
        Point.model_validate({"coordinates": coordinates})


@pytest.mark.parametrize(
    "payload",
    [
        {"type": "LineString", "coordinates": []},
        {"type": "LineString", "coordinates": [[0, 0]]},
        {"type": "MultiLineString", "coordinates": [[[0, 0]]]},
        {"type": "Polygon", "coordinates": []},
        {"type": "Polygon", "coordinates": [[[0, 0]] * 3]},
        {"type": "Polygon", "coordinates": [[*RING[:-1], (1, 1)]]},
        {"type": "MultiPolygon", "coordinates": [[RING[:-1]]]},
        {"type": "Point", "coordinates": [[1, 2]]},
        {"type": "GeometryCollection", "coordinates": []},
        {"type": "GeometryCollection", "geometries": [None]},
        {"type": "Feature", "geometry": None},
        {"coordinates": [1, 2]},
    ],
)
def test_invalid_geometry_structure(payload: dict[str, Any]) -> None:
    with pytest.raises(ValidationError):
        TypeAdapter(Geometry).validate_python(payload)


def test_nested_collection_and_empty_multi_geometries() -> None:
    geometry = GeometryCollection(geometries=[
        GeometryCollection(geometries=[]),
        MultiPoint(coordinates=[]),
        MultiLineString(coordinates=[]),
        MultiPolygon(coordinates=[]),
    ])
    assert TypeAdapter(Geometry).validate_json(
        geometry.model_dump_json(),
    ) == geometry


def test_polygon_holes_and_winding_are_not_rewritten() -> None:
    hole: list[Position] = [(2.0, 2.0), (3.0, 3.0), (4.0, 2.0), (2.0, 2.0)]
    polygon = Polygon(coordinates=[RING, hole])
    assert polygon.coordinates == [RING, hole]
    assert Polygon(coordinates=[list(reversed(RING))]).coordinates == [
        list(reversed(RING)),
    ]


def test_strict_winding_crs() -> None:
    polygon = Polygon(coordinates=[RING], crs=StrictWindingCRS())
    assert polygon.model_dump(mode="json")["crs"] == {
        "type": "name",
        "properties": {"name": "urn:x-mongodb:crs:strictwinding:EPSG:4326"},
    }
    assert Polygon.model_validate(polygon.model_dump()) == polygon
    with pytest.raises(ValidationError, match="single-ring"):
        Polygon(coordinates=[RING, RING], crs=StrictWindingCRS())
    with pytest.raises(ValidationError):
        Polygon.model_validate({
            "coordinates": [RING],
            "crs": {"type": "name", "properties": {"name": "EPSG:3857"}},
        })
    with pytest.raises(ValidationError):
        Point.model_validate({"coordinates": [0, 0], "crs": {}})


def test_document_roundtrip_and_schema() -> None:
    place = Place(name="Cafe", location=Point(coordinates=(37.6, 55.7)))
    assert Place.model_validate(decode(encode(place.model_dump()))) == place
    schema = Place.model_mongodb_schema()
    location = schema["$jsonSchema"]["properties"]["location"]
    assert set(location["required"]) == {"coordinates", "type"}
    assert location["properties"]["type"]["enum"] == ["Point"]
    assert "_id" not in location["properties"]
    positions = location["properties"]["coordinates"]["anyOf"]
    assert [position["minItems"] for position in positions] == [2, 3]
    assert positions[0]["items"][0]["minimum"] == -180
    assert positions[0]["items"][1]["maximum"] == 90


@pytest.mark.parametrize("model", [Polygon, MultiPolygon, MultiLineString])
def test_nonrecursive_geometry_schema(
    model: type[Polygon | MultiPolygon | MultiLineString],
) -> None:
    # Use a Pydantic adapter to exercise aliases and tuple conversion directly.
    schema = TypeAdapter(model).json_schema(
        schema_generator=MongoDBSchemaGenerator,
    )
    assert "$ref" not in str(schema)
    assert "prefixItems" not in str(schema)
    assert "type" in schema["$jsonSchema"]["required"]


def test_recursive_schema_fails_explicitly() -> None:
    class Region(Document):
        shape: GeometryCollection

    with pytest.raises(SchemaGenerationException, match="recursive"):
        Region.model_mongodb_schema()


def test_geometry_union_document_and_recursive_schema() -> None:
    class Region(Document):
        shape: Geometry

    region = Region.model_validate({
        "shape": {"type": "Point", "coordinates": [12, 34]},
    })
    assert isinstance(region.shape, Point)
    assert Region.model_validate(decode(encode(region.model_dump()))) == region
    with pytest.raises(SchemaGenerationException, match="recursive"):
        Region.model_mongodb_schema()


def test_ring_closure_includes_altitude() -> None:
    with pytest.raises(ValidationError, match="identical"):
        Polygon.model_validate({"coordinates": [[
            [0, 0, 1], [1, 0, 1], [1, 1, 1], [0, 0, 2],
        ]]})


def test_assignment_validation_and_extra_fields() -> None:
    point = Point(coordinates=(0, 0))
    with pytest.raises(ValidationError):
        point.coordinates = (181, 0)
    with pytest.raises(ValidationError):
        Point.model_validate({"coordinates": [0, 0], "latitude": 1})


@pytest.mark.parametrize(
    ("kind", "value"),
    [(IndexType.GEO_2DSPHERE, "2dsphere"), (IndexType.GEO_2D, "2d")],
)
def test_geospatial_index_serialization(kind: IndexType, value: str) -> None:
    assert Index("geo", {"location": kind}).model_dump()["key"] == {
        "location": value,
    }
    assert IndexType(value) is kind
