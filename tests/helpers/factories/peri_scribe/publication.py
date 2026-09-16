"""Build inputs for publication tests."""

from __future__ import annotations

import dataclasses
import datetime
import pathlib
import typing

import peri_scribe.publication
import peri_scribe.sources.feeds
import tests.helpers.factories.geography
from peri_scribe.units import units


if typing.TYPE_CHECKING:
    import shapely

NOW = datetime.datetime(2026, 9, 13, tzinfo=datetime.UTC)


STAMP = peri_scribe.publication.FileStamp(size=1, modified_nanoseconds=1)


THRESHOLD = peri_scribe.publication.Threshold(
    area=25.0 * units.acres,
    interval=datetime.timedelta(minutes=5),
)


@dataclasses.dataclass(frozen=True, kw_only=True)
class MappingComparison:
    """Keep source acreages independent of the persisted square-meter measurements.

    Args:
        current_acres: The candidate acreage, or None when it cannot be measured.
        baseline_acres: The published acreage, or None when it cannot be measured.
        baseline_present: Whether a published mapping exists for the fire.
        current_minutes: The candidate's time relative to the published observation.
    """

    current_acres: int | None
    baseline_acres: int | None
    baseline_present: bool
    current_minutes: int


def mapping_candidates(
    comparisons: list[MappingComparison],
) -> dict[
    str,
    tuple[
        peri_scribe.publication.Mapping,
        peri_scribe.publication.PublishedFire | None,
    ],
]:
    """Encode independent comparison data as publication candidates.

    Args:
        comparisons: Current and published observations for distinct fires.

    Returns:
        Candidates whose area units and timestamps match persisted publication data.
    """
    candidates = {}
    for index, item in enumerate(comparisons):
        name = f"Fire {index}"
        identifiers = (f"fire-{index}",)
        current = mapping(
            item.current_acres,
            serial=3,
            identifiers=identifiers,
        ).model_copy(
            update={
                "name": name,
                "observed_at": NOW + datetime.timedelta(minutes=item.current_minutes),
            },
        )
        baseline = (
            peri_scribe.publication.PublishedFire(
                name=name,
                identifiers=identifiers,
                mapping=mapping(
                    item.baseline_acres,
                    serial=2,
                    identifiers=identifiers,
                ).model_copy(update={"observed_at": NOW}),
            )
            if item.baseline_present
            else None
        )
        candidates[name] = (current, baseline)
    return candidates


def mapping(
    acres: float | None,
    *,
    serial: int = 1,
    identifiers: tuple[str, ...] = ("a",),
    captured_at: datetime.datetime = NOW,
) -> peri_scribe.publication.Mapping:
    """Construct source observations with deliberately distinct capture and map dates.

    Args:
        acres: The raw mapped area in acres, or None for an unmeasurable mapping.
        serial: The snapshot serial used to distinguish and order observations.
        identifiers: The fire identifiers associated with the mapping.
        captured_at: The local first-capture time used for provenance.

    Returns:
        A raw source measurement suitable for persisted checkpoints.
    """
    return peri_scribe.publication.Mapping(
        source_file=f"snapshot-{serial}",
        object_id=serial,
        identifiers=identifiers,
        name="Example",
        observed_at=NOW + datetime.timedelta(minutes=serial),
        captured_at=captured_at,
        serial=serial,
        shape=str(acres),
        area_square_meters=(acres * units.acres).m_as("meters ** 2")
        if acres is not None
        else None,
    )


def collection(
    *args: peri_scribe.publication.Mapping,
) -> peri_scribe.publication.Collection:
    """Retain each downloaded snapshot independently of publication.

    Args:
        *args: Source observations to include in the downloaded inventory.

    Returns:
        A complete source inventory containing these observations.
    """
    return peri_scribe.publication.Collection(
        files={item.source_file: STAMP for item in args},
        mappings={item.source_file: (item,) for item in args},
    )


def publication(
    baseline: peri_scribe.publication.Mapping | None,
) -> peri_scribe.publication.Publication:
    """Publication knows which source files were actually processed.

    Args:
        baseline: The previously displayed mapping, or None for an excluded fire.

    Returns:
        The completed baseline, including the zero baseline for excluded fires.
    """
    return peri_scribe.publication.Publication(
        created_at=NOW,
        output=STAMP,
        files={} if baseline is None else {baseline.source_file: STAMP},
        fires={
            "id:a": peri_scribe.publication.PublishedFire(
                identifiers=("a", "alias"),
                name="Example",
                mapping=baseline,
            ),
        },
    )


def write_perimeter_snapshot(
    sources_directory: pathlib.Path,
    geometry: shapely.Geometry | None,
    attributes: dict[str, object],
    *,
    serial: int = 1,
) -> pathlib.Path:
    """Exercise collection with source attributes preserved through real storage.

    Args:
        sources_directory: The isolated directory containing the source snapshots.
        geometry: The source perimeter in WGS84, or None when unavailable.
        attributes: Reported sizes and other attributes to include in the source row.
        serial: The snapshot number used to order observations.

    Returns:
        The stored perimeter snapshot path.
    """
    feed = peri_scribe.sources.feeds.WFIGS_PERIMETERS_FEED
    values = {
        "attr_IncidentName": "Example",
        "attr_ActiveFireCandidate": 1,
        "poly_IRWINID": "{A}",
        "attr_UniqueFireIdentifier": None,
        "attr_POOState": None,
        "attr_POOFips": None,
        "poly_DateCurrent": NOW + datetime.timedelta(minutes=serial),
        "OBJECTID": 123,
        **attributes,
    }
    frame = tests.helpers.factories.geography.geo_frame(
        {name: [value] for name, value in values.items()},
        [geometry],
    )
    path = sources_directory / feed.name / f"000___/{serial:06d},lastEdit=1.gpkg"
    path.parent.mkdir(parents=True, exist_ok=True)
    frame.to_file(path, layer=feed.name, driver="GPKG")
    return path
