"""Typed MongoDB GeoJSON geometries in WGS84 longitude/latitude order.

Structural validation is local; spherical topology is checked by MongoDB.
"""

from __future__ import annotations

from typing import Annotated, Any, Literal, Self

from pydantic import (
    AfterValidator,
    BaseModel,
    ConfigDict,
    Field,
    StrictFloat,
    model_validator,
)

type Longitude = Annotated[
    StrictFloat, Field(ge=-180, le=180, allow_inf_nan=False),
]
type Latitude = Annotated[
    StrictFloat, Field(ge=-90, le=90, allow_inf_nan=False),
]
type Altitude = Annotated[StrictFloat, Field(allow_inf_nan=False)]
type Position = (
    tuple[Longitude, Latitude] | tuple[Longitude, Latitude, Altitude]
)
_POSITION_3D_LENGTH = 3
type LineCoordinates = Annotated[list[Position], Field(min_length=2)]


def _closed_ring(value: list[Position]) -> list[Position]:
    """Require an explicitly closed linear ring.

    Returns:
        The original ring without reordering or adding positions.

    Raises:
        ValueError: If the first and last positions differ.
    """
    if value[0] != value[-1]:
        msg = "a linear ring must have identical first and last positions"
        raise ValueError(msg)
    return value


type LinearRing = Annotated[
    list[Position], Field(min_length=4), AfterValidator(_closed_ring),
]
type PolygonCoordinates = Annotated[
    list[LinearRing], Field(min_length=1),
]


def _require_type(schema: dict[str, Any]) -> None:
    """Require the GeoJSON tag even though constructors supply its default."""
    schema.setdefault("required", []).append("type")


class _Geometry(BaseModel):
    """Geometry payload without a document ID or implicit extra fields."""

    model_config = ConfigDict(
        extra="forbid",
        validate_assignment=True,
        json_schema_extra=_require_type,
    )


class Point(_Geometry):
    """A WGS84 point; optional third ordinate is altitude, not distance."""

    type: Literal["Point"] = "Point"
    coordinates: Position

    @classmethod
    def from_lon_lat(
        cls,
        *,
        longitude: float,
        latitude: float,
        altitude: float | None = None,
    ) -> Self:
        """Create a validated point using explicit coordinate names.

        Returns:
            A point with longitude first and optional altitude last.
        """
        coordinates: Position = (
            (longitude, latitude)
            if altitude is None
            else (longitude, latitude, altitude)
        )
        return cls(coordinates=coordinates)

    @property
    def longitude(self) -> float:
        """Longitude in degrees, between -180 and 180."""
        return self.coordinates[0]

    @property
    def latitude(self) -> float:
        """Latitude in degrees, between -90 and 90."""
        return self.coordinates[1]

    @property
    def altitude(self) -> float | None:
        """Optional altitude in meters; not used for spherical distances."""
        return (
            self.coordinates[2]
            if len(self.coordinates) == _POSITION_3D_LENGTH
            else None
        )


class LineString(_Geometry):
    """A line containing at least two positions."""

    type: Literal["LineString"] = "LineString"
    coordinates: LineCoordinates


class _CRSProperties(BaseModel):
    """MongoDB's supported custom coordinate reference system name."""

    model_config = ConfigDict(extra="forbid")
    name: Literal["urn:x-mongodb:crs:strictwinding:EPSG:4326"] = (
        "urn:x-mongodb:crs:strictwinding:EPSG:4326"
    )


class StrictWindingCRS(BaseModel):
    """MongoDB's query-only strict counterclockwise winding extension."""

    model_config = ConfigDict(extra="forbid")
    type: Literal["name"] = "name"
    properties: _CRSProperties = Field(default_factory=_CRSProperties)


class Polygon(_Geometry):
    """An exterior ring followed by zero or more interior rings.

    MongoDB validates spherical topology. The optional strict-winding CRS
    is a MongoDB query extension for single-ring polygons only.
    """

    type: Literal["Polygon"] = "Polygon"
    coordinates: PolygonCoordinates
    crs: StrictWindingCRS | None = Field(
        default=None, exclude_if=lambda value: value is None,
    )

    @model_validator(mode="after")
    def validate_crs(self) -> Self:
        """Limit MongoDB's custom CRS to single-ring polygons.

        Returns:
            The validated polygon.

        Raises:
            ValueError: If strict winding is combined with interior rings.
        """
        if self.crs is not None and len(self.coordinates) != 1:
            msg = "strict-winding CRS requires a single-ring polygon"
            raise ValueError(msg)
        return self


class MultiPoint(_Geometry):
    """An array of positions."""

    type: Literal["MultiPoint"] = "MultiPoint"
    coordinates: list[Position]


class MultiLineString(_Geometry):
    """An array of lines, each containing at least two positions."""

    type: Literal["MultiLineString"] = "MultiLineString"
    coordinates: list[LineCoordinates]


class MultiPolygon(_Geometry):
    """An array of polygons, each with an exterior ring and optional holes."""

    type: Literal["MultiPolygon"] = "MultiPolygon"
    coordinates: list[PolygonCoordinates]


# PEP 695 aliases are lazy; Pydantic resolves this recursive alias
# automatically when the collection is first validated or used in a schema.
type Geometry = Annotated[
    Point
    | LineString
    | Polygon
    | MultiPoint
    | MultiLineString
    | MultiPolygon
    | GeometryCollection,
    Field(discriminator="type"),
]


class GeometryCollection(_Geometry):
    """A possibly empty collection of geometries, including collections.

    Recursive collections validate in Pydantic but cannot be represented by
    Kover's reference-free MongoDB JSON Schema generator.
    """

    type: Literal["GeometryCollection"] = "GeometryCollection"
    geometries: list[Geometry]
