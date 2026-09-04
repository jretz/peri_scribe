"""Gathering the fire facts a report renders.

The report is assembled from the same derived outputs the KMZ reads: the fire index, the
saved fire scores, and the full and differential history layers. The gathering returns a
frozen :class:`FireReport` whose lists are already selected and ordered, so a renderer
only has to format them.
"""

from __future__ import annotations

import dataclasses
import datetime
import pathlib
import typing

import peri_scribe.fires.differential
import peri_scribe.fires.files
import peri_scribe.fires.index
import peri_scribe.fires.score_files
import peri_scribe.geo.reading
import peri_scribe.kml.builder
import peri_scribe.kml.descriptions
import peri_scribe.kml.fire_data
import peri_scribe.kml.folders
import peri_scribe.models


@dataclasses.dataclass(frozen=True, kw_only=True)
class FireReportEntry:
    """One fire's facts as the report renders them.

    The fire's description carries the same latest-state facts the fire's KMZ balloon
    table shows, so the report's details can include every fact the balloon would; the
    growth over the fast-growth window and the saved score are measures the balloons do
    not show, so they ride alongside as report-only fields.
    """

    name: str
    identifier: str | None = None
    status: peri_scribe.models.FireStatus
    description: peri_scribe.kml.descriptions.FireDescription | None = None
    growth_in_acres: float | None = None
    growth_in_percent: float | None = None
    score: int | None = None


@dataclasses.dataclass(frozen=True, kw_only=True)
class FireReport:
    """The report's fire lists and its per-fire details.

    Each fire list is ordered most-to-least interesting; the detail entries, one per
    distinct fire across the lists, are ordered by name.
    """

    new_notable_fires: tuple[FireReportEntry, ...]
    fastest_growing_by_acres: tuple[FireReportEntry, ...]
    fastest_growing_by_percent: tuple[FireReportEntry, ...]
    top_fires: tuple[FireReportEntry, ...]
    fire_details: tuple[FireReportEntry, ...]


def report_entry(
    fire: peri_scribe.kml.fire_data.FireGeometry,
    scores_by_identifier: typing.Mapping[str, peri_scribe.models.FireScoreEntry],
    scores_by_name: typing.Mapping[str, peri_scribe.models.FireScoreEntry],
    reference_time: datetime.datetime,
) -> FireReportEntry:
    """Return the report facts for one fire.

    The fire's latest-state facts ride along as its description so the report's details
    can show the same data the fire's KMZ balloon shows; its growth over the fast-growth
    window is measured from its perimeters. The score is matched by identifier first and
    then name, mirroring how the KMZ resolves a fire to its saved score.

    Args:
        fire: The fire to describe.
        scores_by_identifier: Score entries keyed by identifier.
        scores_by_name: Score entries without identifiers, keyed by name.
        reference_time: The wall-clock time the report is gathered.

    Returns:
        The fire's report facts.
    """
    growth_in_acres, growth_in_percent = peri_scribe.kml.folders.fire_growth(
        fire,
        reference_time,
    )
    return FireReportEntry(
        name=fire.name,
        identifier=peri_scribe.models.canonical_fire_identifier(fire.identifiers),
        status=fire.status,
        description=fire.description,
        growth_in_acres=growth_in_acres,
        growth_in_percent=growth_in_percent,
        score=peri_scribe.kml.folders.score_value_for_fire(
            fire,
            scores_by_identifier,
            scores_by_name,
        ),
    )


def report_entries(
    fires: typing.Iterable[peri_scribe.kml.fire_data.FireGeometry],
    scores_by_identifier: typing.Mapping[str, peri_scribe.models.FireScoreEntry],
    scores_by_name: typing.Mapping[str, peri_scribe.models.FireScoreEntry],
    reference_time: datetime.datetime,
) -> tuple[FireReportEntry, ...]:
    """Return the report facts for each fire, preserving the input order.

    Args:
        fires: The fires to describe.
        scores_by_identifier: Score entries keyed by identifier.
        scores_by_name: Score entries without identifiers, keyed by name.
        reference_time: The wall-clock time the report is gathered.

    Returns:
        One report entry per fire, in the input order.
    """
    return tuple(
        report_entry(fire, scores_by_identifier, scores_by_name, reference_time)
        for fire in fires
    )


def report_details(
    *sections: tuple[FireReportEntry, ...],
) -> tuple[FireReportEntry, ...]:
    """Return one entry per distinct fire across *sections*, sorted by name.

    A fire is identified by its canonical identifier when it has one, and by its name
    otherwise, mirroring how the KMZ matches a fire to its saved score, so a fire
    mentioned in several sections appears once in the returned details.

    Args:
        sections: The report's fire lists.

    Returns:
        One entry per distinct fire, ordered by name.
    """
    entries_by_identity: dict[str, FireReportEntry] = {}
    for section in sections:
        for entry in section:
            identity = entry.identifier if entry.identifier is not None else entry.name
            entries_by_identity.setdefault(identity, entry)
    return tuple(
        sorted(
            entries_by_identity.values(),
            key=lambda entry: (
                entry.name.casefold(),
                entry.name,
                entry.identifier or "",
            ),
        ),
    )


def gather_report(year_directory: pathlib.Path) -> FireReport:
    """Gather the fire report for *year_directory* from its derived outputs.

    The same index, scores, and history layers that feed the KMZ are read here, so the
    report's lists match the map's top-level views: new and notable fires, the fastest
    growing fires by acres and by percent, and the top fires by score.

    Args:
        year_directory: The year directory that holds the ``derived`` directory.

    Returns:
        The gathered report, with each list ordered most-to-least interesting.
    """
    index = peri_scribe.fires.index.load_fire_index(year_directory)
    scores = peri_scribe.fires.score_files.load_fire_scores(year_directory)
    history_path = peri_scribe.fires.files.history_geopackage_path(year_directory)
    perimeters = peri_scribe.geo.reading.read_layer(
        history_path,
        peri_scribe.fires.files.PERIMETER_LAYER_NAME,
    )
    points = peri_scribe.geo.reading.read_layer(
        history_path,
        peri_scribe.fires.files.POINT_LAYER_NAME,
    )
    differential_path = peri_scribe.fires.differential.differential_geopackage_path(
        year_directory,
    )
    index = peri_scribe.kml.builder.area_qualified_index(index, perimeters, points)
    fire_scores = scores or peri_scribe.models.FireScores(version="", fires=[])
    fires = peri_scribe.kml.fire_data.fire_geometries(
        index,
        perimeters,
        points,
        peri_scribe.geo.reading.read_layer(
            differential_path,
            peri_scribe.fires.files.PERIMETER_LAYER_NAME,
        ),
        scores=fire_scores,
        render_plots=False,
    )
    scores_by_identifier, scores_by_name = peri_scribe.kml.folders.score_maps(
        fire_scores,
    )
    reference_time = datetime.datetime.now(datetime.UTC)
    new_notable_entries = report_entries(
        peri_scribe.kml.folders.new_notable_fires(
            fires,
            fire_scores,
            reference_time,
        ),
        scores_by_identifier,
        scores_by_name,
        reference_time,
    )
    fast_growing_by_acres_entries = report_entries(
        peri_scribe.kml.folders.fast_growing_fires_by_acres(
            fires,
            reference_time,
        ),
        scores_by_identifier,
        scores_by_name,
        reference_time,
    )
    fast_growing_by_percent_entries = report_entries(
        peri_scribe.kml.folders.fast_growing_fires_by_percent(
            fires,
            reference_time,
        ),
        scores_by_identifier,
        scores_by_name,
        reference_time,
    )
    top_fire_entries = report_entries(
        peri_scribe.kml.folders.top_fires(fires, fire_scores),
        scores_by_identifier,
        scores_by_name,
        reference_time,
    )
    return FireReport(
        new_notable_fires=new_notable_entries,
        fastest_growing_by_acres=fast_growing_by_acres_entries,
        fastest_growing_by_percent=fast_growing_by_percent_entries,
        top_fires=top_fire_entries,
        fire_details=report_details(
            new_notable_entries,
            fast_growing_by_acres_entries,
            fast_growing_by_percent_entries,
            top_fire_entries,
        ),
    )
