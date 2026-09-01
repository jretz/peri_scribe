"""Dataclasses and constants for peri_scribe."""

from __future__ import annotations

import dataclasses
import datetime
import enum
import pathlib
import re
import typing
from typing import TYPE_CHECKING

import pydantic


if TYPE_CHECKING:
    import geopandas
    import pyproj
    import shapely


GEOMETRY_COLUMN_NAME = "geom"

# The geometry column name GeoPackages report when read back: geopandas/pyogrio name the
# geometry column ``geometry`` regardless of the name it was stored under, so frames
# fetched (named ``geom``) and frames read back (named ``geometry``) must be renamed to
# one name before they are merged.
GEOPACKAGE_GEOMETRY_COLUMN_NAME = "geometry"

# Column names used by the ArcGIS feature services and the GeoPackages that store them.
OBJECT_ID_COLUMN_NAME = "OBJECTID"
SHAPE_COLUMN_NAME = "SHAPE"

# Minimum plausible coordinate magnitude, in meters, for a projected reference. Smaller
# magnitudes are indistinguishable from degrees.
MINIMUM_PROJECTED_MAGNITUDE_IN_METERS = 1_000.0

# Fallback maximum coordinate magnitude, in meters, for a projected reference with no
# known area of use; roughly the widest extent any Earth-based projection produces.
PROJECTED_MAXIMUM_MAGNITUDE_FALLBACK_IN_METERS = 25_000_000.0

# EPSG ids for the spatial references the project reads and writes.
WGS84_SPATIAL_REFERENCE_ID = 4326
NAD83_SPATIAL_REFERENCE_ID = 4269
CALIFORNIA_ALBERS_SPATIAL_REFERENCE_ID = 3310

# The earliest representable aware UTC datetime, used as an ordering floor when a fire
# observation has no timestamp.
EARLIEST_DATETIME = datetime.datetime.min.replace(tzinfo=datetime.UTC)


@dataclasses.dataclass(frozen=True, kw_only=True)
class LayerData:
    name: str
    dataframe: geopandas.GeoDataFrame


class FireStatus(enum.Enum):
    """Whether a fire is active or inactive."""

    ACTIVE = "active"
    INACTIVE = "inactive"


class BorderClassification(enum.Enum):
    """Where a fire sits relative to the California state boundary."""

    INSIDE_CALIFORNIA = "inside_california"
    INSIDE_CALIFORNIA_NEAR_BORDER = "inside_california_near_border"
    CROSSES_CALIFORNIA_BORDER = "crosses_california_border"
    OUTSIDE_CALIFORNIA_NEAR_BORDER = "outside_california_near_border"
    OUTSIDE_CALIFORNIA = "outside_california"


class BorderSignal(enum.Enum):
    """The evidence signals that contributed to a border classification."""

    GEOMETRY_OUTSIDE = "geometry_outside"
    GEOMETRY_NEAR = "geometry_near"
    EXTENT_DISAGREEMENT = "extent_disagreement"
    IDENTIFIER_UNIT = "identifier_unit"


GLOBALLY_UNIQUE_IDENTIFIER_PATTERN = re.compile(
    r"^[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}$",
    re.IGNORECASE,
)

UNIQUE_FIRE_IDENTIFIER_PATTERN = re.compile(
    r"^20\d{2}-[a-z0-9]+-\d+$",
    re.IGNORECASE,
)

SEPARATOR_PATTERN = re.compile(r"[-_/]+")


def is_globally_unique_identifier(value: str) -> bool:
    """Return True when *value* is a hyphenated 128-bit GUID.

    Args:
        value: A normalized identifier to classify.

    Returns:
        True when *value* matches the GUID shape.

    Examples:
        >>> is_globally_unique_identifier("286b7f1d-8945-4a5d-9d81-5235c18af1fe")
        True

        >>> is_globally_unique_identifier("2025-LNU-123456")
        False
    """
    return GLOBALLY_UNIQUE_IDENTIFIER_PATTERN.fullmatch(value) is not None


def is_unique_fire_identifier(value: str) -> bool:
    """Return True when *value* is a ``YYYY-UNIT-######`` fire identifier.

    Args:
        value: A normalized identifier to classify.

    Returns:
        True when *value* matches the unique fire identifier shape.

    Examples:
        >>> is_unique_fire_identifier("2025-LNU-123456")
        True

        >>> is_unique_fire_identifier("286b7f1d-8945-4a5d-9d81-5235c18af1fe")
        False
    """
    if is_globally_unique_identifier(value):
        return False
    return UNIQUE_FIRE_IDENTIFIER_PATTERN.fullmatch(value) is not None


def canonical_fire_identifier(identifiers: typing.Iterable[str]) -> str | None:
    """Return the most canonical identifier among *identifiers*.

    A unique fire identifier (``YYYY-UNIT-######``) is preferred over a GUID, which is
    preferred over any other identifier. Ties within a kind are broken by sorting, so
    the result is stable.

    Args:
        identifiers: The normalized identifiers known for a fire.

    Returns:
        The canonical identifier, or None when there are none.

    Examples:
        >>> canonical_fire_identifier(["other", "2025-LNU-123456", "guid"])
        '2025-LNU-123456'
    """
    unique = sorted(
        identifier
        for identifier in identifiers
        if is_unique_fire_identifier(identifier)
    )
    if unique:
        return unique[0]
    globally_unique = sorted(
        identifier
        for identifier in identifiers
        if is_globally_unique_identifier(identifier)
    )
    if globally_unique:
        return globally_unique[0]
    others = sorted(set(identifiers))
    return others[0] if others else None


def normalize_fire_name(name: str) -> str:
    """Normalize a fire name for comparison.

    Names are case-folded, surrounding whitespace is stripped, runs of internal
    whitespace are collapsed, and separator characters (``-``, ``_``, ``/``) are treated
    as spaces so that ``SANTA-ROSA`` and ``SANTA ROSA`` compare equal.

    Args:
        name: The fire name to normalize.

    Returns:
        The normalized name.

    Examples:
        >>> normalize_fire_name("  Santa-Rosa / Fire  ")
        'santa rosa fire'
    """
    return " ".join(SEPARATOR_PATTERN.sub(" ", name.casefold()).split())


@dataclasses.dataclass(frozen=True, kw_only=True)
class MissionName:
    """The fire-name parts of a mapping mission code.

    A mission code such as ``CA-LNU-RUMSEY-UPDATED-N40Y`` names the fire both as the
    source recorded it (``name``) and with mapping-revision markers removed
    (``base_name``), so an updated re-mapping can still be matched to the original fire.
    """

    name: str | None = None
    base_name: str | None = None


@dataclasses.dataclass(frozen=True, kw_only=True)
class FireRecord:
    """One fire as observed in a single source row.

    A record carries every identifier the row provides, every name spelling the row is
    known by (normalized), and the row's geometry and observation time. Geometry and
    time gate name-based grouping so distinct fires that share a name are not merged.
    """

    name: str
    status: FireStatus
    identifiers: frozenset[str] = dataclasses.field(default_factory=frozenset)
    names: frozenset[str] = dataclasses.field(default_factory=frozenset)
    geometry: shapely.Geometry | None = None
    observed_at: datetime.datetime | None = None
    mission: str | None = None
    point_of_origin_state: str | None = None
    point_of_origin_fips: str | None = None


@dataclasses.dataclass(frozen=True, kw_only=True)
class Fire:
    """A fire, identified by name, a canonical identifier, and every alias.

    ``identifier`` is the canonical identifier: the preferred unique fire identifier
    (``YYYY-UNIT-######``) when one is known, else a GUID. ``aliases`` holds every
    normalized identifier the fire is known by, including the canonical one. When the
    fire is part of a complex, ``complex`` points at the FireComplex that owns it.
    """

    name: str
    status: FireStatus
    identifier: str | None = None
    aliases: frozenset[str] = dataclasses.field(default_factory=frozenset)
    complex: FireComplex | None = dataclasses.field(
        default=None,
        compare=False,
        repr=False,
    )


@dataclasses.dataclass(frozen=True, kw_only=True)
class FireComplex:
    """A complex of fires, linked to each of its member fires.

    A complex is an incident with child fires. Constructing a FireComplex sets each
    member fire's ``complex`` back-reference, so the link between a fire and its complex
    is circular.
    """

    name: str
    identifier: str
    fires: frozenset[Fire]

    def __post_init__(self) -> None:
        for fire in self.fires:
            object.__setattr__(fire, "complex", self)


@dataclasses.dataclass(frozen=True, kw_only=True)
class ComplexMembership:
    """A fire's membership in a complex, as observed in a GeoPackage layer."""

    fire_identifier: str
    complex_identifier: str
    complex_name: str


@dataclasses.dataclass(frozen=True, kw_only=True)
class FireSources:
    """A distinct fire and the GeoPackage files that mention it.

    The same fire can appear in many snapshots across one or more sources, so ``paths``
    holds every GeoPackage file whose rows record that fire.
    """

    fire: Fire
    paths: tuple[pathlib.Path, ...]


class FireIndexComplex(pydantic.BaseModel):
    """A fire's complex membership as recorded in the fire source index."""

    name: str
    identifier: str


class FireClassification(pydantic.BaseModel):
    """A fire's border classification and the evidence behind it."""

    classification: BorderClassification
    distance_to_boundary_in_meters: float
    outside_area_fraction: float
    inside_area_fraction: float
    wfigs_to_firis_area_ratio: float | None = None
    signals: list[BorderSignal] = pydantic.Field(default_factory=list)


class FireIndexEntry(pydantic.BaseModel):
    """One fire's entry in the fire source index."""

    name: str
    status: typing.Literal["active", "inactive"]
    identifier: str | None = None
    aliases: list[str] = pydantic.Field(default_factory=list)
    complex: FireIndexComplex | None = None
    classification: FireClassification | None = None
    paths: list[str]


class FireIndex(pydantic.BaseModel):
    """The fire source index: every fire and the files that mention it."""

    version: str
    fires: list[FireIndexEntry]


class FireScoreComponents(pydantic.BaseModel):
    """The per-signal point contributions to a fire's score."""

    size: int
    growth: int
    first_mapping: int
    buildings: int
    evacuation: int
    importance: int


class FireScoreEntry(pydantic.BaseModel):
    """One fire's score, the current components, and why it has that score."""

    name: str
    identifier: str | None = None
    score: int
    components: FireScoreComponents
    explanation: str


class FireScores(pydantic.BaseModel):
    """Every fire's score for the season, ordered most-to-least interesting."""

    version: str
    fires: list[FireScoreEntry]


@dataclasses.dataclass(frozen=True)
class SpatialReferenceDomain:
    """Plausible coordinate magnitude bands for a spatial reference."""

    crs: pyproj.CRS
    bands: tuple[float, float, float, float]  # x and y (minimum, maximum) magnitudes
    description: str


@dataclasses.dataclass(frozen=True, kw_only=True)
class SpatialReferenceSelection:
    """Result of selecting a spatial reference wkid from candidates.

    When a wkid is chosen, ``warning`` holds the text to log about excluded candidates,
    if any. When no wkid can be chosen, ``failure_message`` explains why.
    """

    wkid: int | None
    warning: str | None = None
    failure_message: str = ""
