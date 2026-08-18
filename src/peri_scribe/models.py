"""Dataclasses and constants for peri_scribe."""

from __future__ import annotations

import dataclasses
import enum
import importlib.resources
import json
import pathlib
import typing
from typing import TYPE_CHECKING

import pydantic

import peri_scribe.feed_types


if TYPE_CHECKING:
    import geopandas
    import pyproj


GEOMETRY_COLUMN_NAME = "geom"

# Minimum plausible magnitude for coordinates in a projected (metre) reference. Smaller
# magnitudes are indistinguishable from degrees.
MINIMUM_PROJECTED_MAGNITUDE = 1_000.0

# Fallback maximum magnitude for a projected reference with no known area of use;
# roughly the widest extent any Earth-based projection produces.
PROJECTED_MAXIMUM_MAGNITUDE_FALLBACK = 25_000_000.0


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


@dataclasses.dataclass(frozen=True, kw_only=True)
class Fire:
    """A fire, identified by name and a stable identifier when one is known.

    The identifier is normalized (case-folded, stripped of surrounding braces) so that
    equal identifiers match regardless of formatting. When the fire is part of a
    complex, `complex` points at the FireComplex that owns it.
    """

    name: str
    status: FireStatus
    identifier: str | None = None
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
