# GeoJSON

Kover provides Pydantic v2 geometry models in `kover.geo` for MongoDB's
[GeoJSON geometry format](https://www.mongodb.com/docs/manual/reference/geojson/).
They are embedded `BaseModel` objects, not documents: they have no `_id`.
No additional dependency or BSON codec configuration is needed.

## Store a typed location

```python
from kover import Document, Index, IndexType
from kover.geo import Point


class Place(Document):
    name: str
    location: Point


# Inside an async function, with an open client:
places = await client.demo.create_collection("places")
await places.set_validator(Place.model_mongodb_schema())
await places.create_indexes(
    Index("location_2dsphere", {"location": IndexType.GEO_2DSPHERE}),
)

place = Place(
    name="Cafe",
    location=Point(coordinates=(37.6173, 55.7558)),
)
identifier = await places.insert_one(place)
loaded = await places.find_one({"_id": identifier}, cls=Place)
assert loaded is not None
assert loaded.location.coordinates == (37.6173, 55.7558)
```

The `type` tag defaults to the class's GeoJSON name. `model_dump()` preserves
coordinate tuples in Python mode; Elune encodes them as BSON arrays.
`model_dump(mode="json")` produces ordinary JSON arrays:

```python
assert place.location.model_dump(mode="json") == {
    "type": "Point",
    "coordinates": [37.6173, 55.7558],
}
```

## Coordinates and validation

Positions use **longitude, latitude**, optionally followed by altitude:

```python
point = Point(coordinates=(37.6173, 55.7558))
elevated = Point(coordinates=(37.6173, 55.7558, 150.0))
```

- Longitude is between **-180 and 180**, inclusive.
- Latitude is between **-90 and 90**, inclusive.
- Two or three ordinates are accepted; altitude must be finite. MongoDB
  spherical queries use longitude/latitude, not altitude for 3D distance.
- Coordinates accept numbers, including integers, normalized to floats.
  Strings, booleans, `NaN`, and infinity are rejected.
- `LineString` requires at least two positions.
- Every polygon requires an exterior ring. Each ring requires at least
  four positions with identical first and last positions, including altitude.
- The exterior ring comes first, followed by holes.
- Multi-geometries and collections may be empty structurally. This does not
  guarantee they are useful or accepted by every server indexing operation.
- Extra fields are rejected rather than silently discarded. These models
  intentionally do not model `bbox`, foreign members, `Feature`, or
  `FeatureCollection`; they are not a general-purpose RFC 7946 reader.

Kover does **not** reorder rings, close them automatically, reverse winding,
or perform planar approximations of spherical geometry. MongoDB checks
topology when indexing/querying: self-intersections, containment of holes,
overlapping holes, shared edges, degenerate geometry, and other server rules.
Without a geospatial index or query, merely storing a dictionary does not
ensure that MongoDB has checked its topology.

The models use WGS84, as MongoDB does. MongoDB's spherical edges and polygon
semantics are not identical to the Cartesian edges described by RFC 7946.
Use MongoDB's documentation as the authority for database behavior.

Assignment to model fields is validated. As with ordinary Pydantic models,
in-place list mutations, `model_construct()`, and unvalidated model copies
can bypass validation; rebuild from serialized data to validate such changes.

## Supported geometries

```python
from kover.geo import (
    GeometryCollection,
    LineString,
    MultiLineString,
    MultiPoint,
    MultiPolygon,
    Point,
    Polygon,
)

point = Point(coordinates=(40, 5))
line = LineString(coordinates=[(40, 5), (41, 6)])
polygon = Polygon(coordinates=[[
    (0, 0), (3, 6), (6, 1), (0, 0),
]])
points = MultiPoint(coordinates=[(40, 5), (41, 6)])
lines = MultiLineString(coordinates=[[(40, 5), (41, 6)]])
polygons = MultiPolygon(coordinates=[polygon.coordinates])
collection = GeometryCollection(geometries=[point, line, polygon])
```

`Position` and `LinearRing` are exported annotated type aliases. `Geometry`
is a discriminated union of all seven geometry types:

```python
from pydantic import TypeAdapter

from kover.geo import Geometry

geometry = TypeAdapter(Geometry).validate_python({
    "type": "Point",
    "coordinates": [40, 5],
})


class Region(Document):
    shape: Geometry
```

A discriminator tag is required when loading the union. Nested
`GeometryCollection` values work in Python, JSON, and BSON, although MongoDB
may impose additional restrictions on particular operations.

## MongoDB schema generation

Concrete nonrecursive models (`Point`, `LineString`, `Polygon`, and their
multi variants) work with `Document.model_mongodb_schema()`. The generated
schema describes tags, numeric bounds, array lengths, and nested shapes.
It requires the `type` field even though Python constructors supply a default.
Coordinate numbers serialized from models are BSON doubles; the generated
schema consequently requires doubles, not raw integer coordinates.

Ring closure and CRS/ring cross-field checks are Python validators, not
MongoDB `$jsonSchema` constraints. Likewise, topology is not expressed by
the schema. Do not treat schema validation as a replacement for a geoindex.

**Recursive schema limitation:** `Geometry` and `GeometryCollection` permit
arbitrarily nested collections. MongoDB `$jsonSchema` cannot use recursive
`$ref`, so Kover raises `SchemaGenerationException` rather than generating
an incomplete validator. Use a concrete geometry field or a nonrecursive
union of concrete types when database schema generation is needed.

## Indexes

Use `IndexType.GEO_2DSPHERE` for GeoJSON and spherical queries.
`IndexType.GEO_2D` is for legacy coordinate pairs and flat geometry, not
general GeoJSON. Existing `2dsphere` and `2d` indexes can be read with
`list_indexes()`.

`2dsphere` indexes are always sparse: MongoDB omits documents whose indexed
field is missing, null, or an empty array. This does not mean every empty
GeoJSON geometry is a valid index entry.

**Migration:** `IndexType.GEOSPATIAL` was removed. Its old `"geospatial"`
value was not a valid MongoDB index type. Replace it with
`IndexType.GEO_2DSPHERE` or `IndexType.GEO_2D` as appropriate.

## Queries

Queries remain ordinary MongoDB dictionaries. Use `.model_dump()` for
`$geometry`, not the model instance itself.

### Nearest places

```python
origin = Point(coordinates=(37.6173, 55.7558))
nearby = await places.find({
    "location": {
        "$near": {
            "$geometry": origin.model_dump(),
            "$maxDistance": 1000,
        },
    },
}, cls=Place).to_list()
```

`$near` returns nearest-first results and requires a geospatial index.
For GeoJSON, `$minDistance` and `$maxDistance` are in meters. `$nearSphere`
can be used with the same GeoJSON point structure. Server versions may
restrict `$near`, `$nearSphere`, and `$geoNear` inputs to `Point`.

### Containment and intersection

```python
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

intersecting = await places.find({
    "location": {"$geoIntersects": {"$geometry": area.model_dump()}},
}, cls=Place).to_list()
```

### Return distances with `$geoNear`

```python
results = await places.aggregate([
    # Find nearest documents and attach their distance in meters.
    {"$geoNear": {
        "near": origin.model_dump(),
        "key": "location",
        "distanceField": "distance_meters",
        "spherical": True,
        "maxDistance": 1000,
    }},
    {"$limit": 10},
]).to_list()
```

`$geoNear` must be the first pipeline stage and requires a geospatial index.
The results are dictionaries because `distance_meters` is not a `Place` field.

## Large polygons and MongoDB's custom CRS

With the default CRS, polygons larger than a hemisphere may be interpreted
as their complementary region. MongoDB provides a strict counterclockwise
winding extension for **single-ring polygons** in `$geoWithin` and
`$geoIntersects` queries:

```python
from kover.geo import StrictWindingCRS

large_area = Polygon(
    coordinates=[[
        (-100, -60), (100, -60), (100, 60), (-100, 60), (-100, -60),
    ]],
    crs=StrictWindingCRS(),
)
```

The helper emits `urn:x-mongodb:crs:strictwinding:EPSG:4326`. Kover validates
its shape and the single-ring requirement, not spherical winding direction
or area. This is a MongoDB query extension, not RFC 7946 CRS support; do not
use it as a general stored-data CRS or with `$near`/`$geoNear`.

## Run the example and tests

```bash
uv run python examples/geo_json.py
uv run pytest tests/unit/models/test_geo.py -q
KOVER_RUN_INTEGRATION=1 uv run pytest tests/integration/test_geo.py -v
```

The example uses a temporary database and removes it in `finally`. Connection
configuration uses `MONGO_HOST`, `MONGO_PORT`, and optional `MONGO_USER`,
`MONGO_PASSWORD`, `MONGO_AUTH_DB`, as in the integration test suite.

References: [MongoDB GeoJSON](https://www.mongodb.com/docs/manual/reference/geojson/),
[`$geometry`](https://www.mongodb.com/docs/manual/reference/operator/query/geometry/),
[RFC 7946](https://www.rfc-editor.org/rfc/rfc7946).