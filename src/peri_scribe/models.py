"""Dataclasses and constants for peri_scribe."""

from __future__ import annotations

import dataclasses
import datetime
import enum
import importlib.resources
import json
import pathlib
import re
import typing
from typing import TYPE_CHECKING

import pydantic

import peri_scribe.feed_types


if TYPE_CHECKING:
    import geopandas
    import pyproj
    import shapely


GEOMETRY_COLUMN_NAME = "geom"

# Minimum plausible coordinate magnitude, in meters, for a projected reference.
# Smaller magnitudes are indistinguishable from degrees.
MINIMUM_PROJECTED_MAGNITUDE_IN_METERS = 1_000.0

# Fallback maximum coordinate magnitude, in meters, for a projected reference with no
# known area of use; roughly the widest extent any Earth-based projection produces.
PROJECTED_MAXIMUM_MAGNITUDE_FALLBACK_IN_METERS = 25_000_000.0


def load_feeds_config() -> list[dict[str, typing.Any]]:
    """Read the raw feed configuration from the JSON file on disk.

    Returns:
        The parsed feed configuration as a list of dictionaries.
    """
    config_path = importlib.resources.files("peri_scribe").joinpath("feeds.json")
    return json.loads(config_path.read_text())


def build_feeds(
    configs: list[dict[str, typing.Any]],
) -> typing.Iterator[peri_scribe.feed_types.Feed]:
    """Yield feed instances built from configuration dictionaries.

    Each dictionary must describe an ArcGIS feed: a ``feed_type`` of ``"ArcGISFeed"``
    plus the fields that feed class declares. Unknown configuration keys and values of
    the wrong type are rejected with a validation error.

    Yields:
        One feed instance per configuration dictionary.
    """
    for config in configs:
        yield peri_scribe.feed_types.ArcGISFeed.model_validate(config)


FEEDS: list[peri_scribe.feed_types.Feed] = list(build_feeds(load_feeds_config()))


@dataclasses.dataclass(frozen=True, kw_only=True)
class LayerData:
    name: str
    dataframe: geopandas.GeoDataFrame


class FireStatus(enum.Enum):
    """Whether a fire is active or inactive."""

    ACTIVE = "active"
    INACTIVE = "inactive"


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
    """
    return GLOBALLY_UNIQUE_IDENTIFIER_PATTERN.fullmatch(value) is not None


def is_unique_fire_identifier(value: str) -> bool:
    """Return True when *value* is a ``YYYY-UNIT-######`` fire identifier.

    Args:
        value: A normalized identifier to classify.

    Returns:
        True when *value* matches the unique fire identifier shape.
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
    """
    return " ".join(SEPARATOR_PATTERN.sub(" ", name.casefold()).split())


@dataclasses.dataclass(frozen=True, kw_only=True)
class MissionName:
    """The fire-name parts of a mapping mission code.

    A mission code such as ``CA-LNU-RUMSEY-UPDATED-N40Y`` names the fire both as the
    source recorded it (`name`) and with mapping-revision markers removed (`base_name`),
    so an updated re-mapping can still be matched to the original fire.
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


@dataclasses.dataclass(frozen=True, kw_only=True)
class Fire:
    """A fire, identified by name, a canonical identifier, and every alias.

    `identifier` is the canonical identifier: the preferred unique fire identifier
    (``YYYY-UNIT-######``) when one is known, else a GUID. `aliases` holds every
    normalized identifier the fire is known by, including the canonical one. When the
    fire is part of a complex, `complex` points at the FireComplex that owns it.
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
    member fire's `complex` back-reference, so the link between a fire and its complex
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


class FireIndexEntry(pydantic.BaseModel):
    """One fire's entry in the fire source index."""

    name: str
    status: typing.Literal["active", "inactive"]
    identifier: str | None = None
    aliases: list[str] = pydantic.Field(default_factory=list)
    complex: FireIndexComplex | None = None
    paths: list[str]


class FireIndex(pydantic.BaseModel):
    """The fire source index: every fire and the files that mention it."""

    version: str
    fires: list[FireIndexEntry]


@dataclasses.dataclass(frozen=True)
class SpatialReferenceDomain:
    """Plausible coordinate magnitude bands for a spatial reference."""

    crs: pyproj.CRS
    bands: tuple[float, float, float, float]  # x and y (minimum, maximum) magnitudes
    description: str


@dataclasses.dataclass(frozen=True, kw_only=True)
class SpatialReferenceSelection:
    """Result of selecting a spatial reference wkid from candidates.

    When a wkid is chosen, `warning` holds the text to log about excluded candidates, if
    any. When no wkid can be chosen, `failure_message` explains why.
    """

    wkid: int | None
    warning: str | None = None
    failure_message: str = ""
