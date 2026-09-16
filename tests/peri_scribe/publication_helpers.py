"""Provide data builders and stand-ins for publication tests."""

from __future__ import annotations

import dataclasses
import datetime
import pathlib
import typing

import hypothesis.strategies

import peri_scribe.publication
import peri_scribe.sources.feeds
import tests.factories
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


@hypothesis.strategies.composite
def mapping_decision_cases(
    draw: hypothesis.strategies.DrawFn,
) -> tuple[list[MappingComparison], int]:
    """Generate competing changes, missing measurements, and exact threshold boundaries.

    Args:
        draw: The current example's strategy sampler.

    Returns:
        Independent per-fire observations and a positive threshold measured in acres.
    """
    acreage = hypothesis.strategies.one_of(
        hypothesis.strategies.none(),
        hypothesis.strategies.integers(0, 10_000),
    )
    comparisons = draw(
        hypothesis.strategies.lists(
            hypothesis.strategies.builds(
                MappingComparison,
                current_acres=acreage,
                baseline_acres=acreage,
                current_minutes=hypothesis.strategies.integers(-2, 2),
            ),
            max_size=8,
        ),
    )
    changes = {
        abs(
            item.current_acres
            - ((item.baseline_acres or 0) if item.baseline_present else 0),
        )
        for item in comparisons
        if item.current_acres is not None
        and (not item.baseline_present or item.baseline_acres is not None)
    }
    boundaries = sorted(changes - {0})
    threshold = hypothesis.strategies.integers(1, 10_000)
    if boundaries:
        threshold |= hypothesis.strategies.sampled_from(boundaries)
    return comparisons, draw(threshold)


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


@hypothesis.strategies.composite
def mapping_snapshots(
    draw: hypothesis.strategies.DrawFn,
) -> dict[str, tuple[peri_scribe.publication.Mapping, ...]]:
    """Exercise alias chains without conflating different geometries or unnamed fires.

    Args:
        draw: The current example's strategy sampler.

    Returns:
        Snapshots with repeated shapes, shared aliases, and varied capture dates.
    """
    rows = draw(
        hypothesis.strategies.lists(
            hypothesis.strategies.tuples(
                hypothesis.strategies.sets(
                    hypothesis.strategies.sampled_from(["a", "b", "c", "d"]),
                    max_size=3,
                ),
                hypothesis.strategies.integers(0, 2),
                hypothesis.strategies.integers(0, 30),
            ),
            max_size=12,
        ),
    )
    measurements = [
        mapping(
            100,
            serial=index,
            identifiers=tuple(sorted(identifiers)),
            captured_at=NOW + datetime.timedelta(days=day),
        ).model_copy(update={"shape": f"shape-{shape}"})
        for index, (identifiers, shape, day) in enumerate(rows)
    ]
    return collection(*measurements).mappings


def earliest_linked_capture(
    target: peri_scribe.publication.Mapping,
    measurements: list[peri_scribe.publication.Mapping],
) -> datetime.datetime:
    """Find the earliest same-shape capture by following overlapping alias sets.

    Args:
        target: The mapping whose first capture is required.
        measurements: Every snapshot's original measurements.

    Returns:
        The earliest time reachable through identifiers for the same shape, retaining
        the original timestamp when there are no identifiers.
    """
    identifiers = set(target.identifiers)
    related = [target]
    remaining = [item for item in measurements if item.shape == target.shape]
    while remaining:
        connected = [
            item for item in remaining if identifiers.intersection(item.identifiers)
        ]
        if not connected:
            break
        related.extend(connected)
        identifiers.update(
            identifier for item in connected for identifier in item.identifiers
        )
        remaining = [item for item in remaining if item not in connected]
    return min(item.captured_at for item in related)


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
    frame = tests.factories.geo_frame(
        {name: [value] for name, value in values.items()},
        [geometry],
    )
    path = sources_directory / feed.name / f"000___/{serial:06d},lastEdit=1.gpkg"
    path.parent.mkdir(parents=True, exist_ok=True)
    frame.to_file(path, layer=feed.name, driver="GPKG")
    return path


def make_snapshot_measurement_recorder(
    *,
    reads: list[pathlib.Path],
) -> typing.Callable[..., tuple[peri_scribe.publication.Mapping, ...]]:
    """Create a callback with controlled dependencies.

    Record expensive reads while exercising real inventory and cache I/O.

    Args:
        reads: Shared list recording expensive snapshot measurements.

    Returns:
        The callback bound to the supplied dependencies.
    """

    def measure(
        path: pathlib.Path,
        _sources: pathlib.Path,
        captured: datetime.datetime,
    ) -> tuple[peri_scribe.publication.Mapping, ...]:
        """Record expensive reads while exercising real inventory and cache I/O.

        Args:
            path: The source snapshot whose measurement request is recorded.
            _sources: The sources root accepted to match the reader's signature; unused.
            captured: The actual capture time supplied by collection.

        Returns:
            A source observation with the actual collection timestamp.
        """
        reads.append(path)
        return (mapping(100, captured_at=captured),)

    return measure
