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

import geopandas

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
import peri_scribe.report.locations
import peri_scribe.sources.external_sources


@dataclasses.dataclass(frozen=True, kw_only=True)
class FireReportEntry:
    """One fire's facts as the report renders them.

    The fire's description carries the same latest-state facts the fire's KMZ balloon
    table shows, so the report's details can include every fact the balloon would; the
    growth over the fast-growth window, the saved score, and the nearest-city location
    are measures the balloons do not show, so they ride alongside as report-only fields.
    """

    name: str
    identifier: str | None = None
    status: peri_scribe.models.FireStatus
    description: peri_scribe.kml.descriptions.FireDescription | None = None
    growth_in_acres: float | None = None
    growth_in_percent: float | None = None
    score: int | None = None
    location: str | None = None


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


def fire_identity(fire: peri_scribe.kml.fire_data.FireGeometry) -> str:
    """Return the report identity of *fire*: its canonical identifier, else its name.

    The identity is the one the report uses to tell fires apart, so two fires that share
    a name but not an identifier stay distinct, and a fire without identifiers is
    identified by its name.

    Args:
        fire: The fire to identify.

    Returns:
        The fire's report identity.
    """
    identifier = peri_scribe.models.canonical_fire_identifier(fire.identifiers)
    return fire.name if identifier is None else identifier


def read_cities_layer(year_directory: pathlib.Path) -> geopandas.GeoDataFrame:
    """Read the major cities layer for *year_directory*, or return an empty frame.

    The layer lives at the fixed path the major-cities external source writes, and a
    year that has not fetched it yet yields an empty frame so the report can still be
    gathered without one.

    Args:
        year_directory: The year directory that holds the ``sources`` directory.

    Returns:
        The major cities layer's features, or an empty frame when the layer is absent.
    """
    source = peri_scribe.sources.external_sources.MAJOR_CITIES_SOURCE
    path = peri_scribe.sources.external_sources.output_path(year_directory, source)
    if not path.is_file():
        return geopandas.GeoDataFrame()
    return peri_scribe.geo.reading.read_layer(path, source.layer_name or source.name)


def fire_location(
    fire: peri_scribe.kml.fire_data.FireGeometry,
    cities: geopandas.GeoDataFrame,
) -> str | None:
    """Return *fire*'s nearest-city location phrase, or None when it has none.

    The fire's latest perimeter bounds its interior, and the phrase names the city in
    *cities* closest to that interior, like ``15 mi ESE of Portland, OR``. A fire with
    no mapped perimeter has only its point location, so the phrase is measured from that
    point instead. A fire with neither geometry, and a year without cities, leave the
    location unknown.

    Args:
        fire: The fire to locate.
        cities: The major cities to choose among.

    Returns:
        The fire's location phrase, or None.
    """
    if fire.perimeters:
        location_geometry = fire.perimeters[-1].geometry
        if location_geometry is None or location_geometry.is_empty:
            location_geometry = fire.point
    else:
        location_geometry = fire.point
    if location_geometry is None or location_geometry.is_empty:
        return None
    nearest = peri_scribe.report.locations.nearest_city(location_geometry, cities)
    if nearest is None:
        return None
    return peri_scribe.report.locations.location_text(nearest)


def fire_locations(
    fires: typing.Iterable[peri_scribe.kml.fire_data.FireGeometry],
    cities: geopandas.GeoDataFrame,
) -> dict[str, str]:
    """Return each located fire's phrase keyed by its report identity.

    A fire without an interior or without a usable city contributes no entry, and a fire
    that repeats in *fires* keeps its first phrase, so the caller can hand the result to
    :func:`report_entries` unchanged.

    Args:
        fires: The fires to locate.
        cities: The major cities to choose among.

    Returns:
        The location phrase of each located fire, keyed by report identity.
    """
    locations_by_identity: dict[str, str] = {}
    for fire in fires:
        location = fire_location(fire, cities)
        if location is not None:
            locations_by_identity.setdefault(fire_identity(fire), location)
    return locations_by_identity


def report_entry(
    fire: peri_scribe.kml.fire_data.FireGeometry,
    scores_by_identifier: typing.Mapping[str, peri_scribe.models.FireScoreEntry],
    scores_by_name: typing.Mapping[str, peri_scribe.models.FireScoreEntry],
    reference_time: datetime.datetime,
    *,
    location: str | None = None,
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
        location: The fire's nearest-city location phrase, or None when it has none.

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
        location=location,
    )


def report_entries(
    fires: typing.Iterable[peri_scribe.kml.fire_data.FireGeometry],
    scores_by_identifier: typing.Mapping[str, peri_scribe.models.FireScoreEntry],
    scores_by_name: typing.Mapping[str, peri_scribe.models.FireScoreEntry],
    reference_time: datetime.datetime,
    *,
    locations_by_identity: typing.Mapping[str, str] | None = None,
) -> tuple[FireReportEntry, ...]:
    """Return the report facts for each fire, preserving the input order.

    Each fire's location phrase is looked up in *locations_by_identity* by the fire's
    report identity, so a caller that computed the phrases once can attach them to the
    fires that appear in several lists.

    Args:
        fires: The fires to describe.
        scores_by_identifier: Score entries keyed by identifier.
        scores_by_name: Score entries without identifiers, keyed by name.
        reference_time: The wall-clock time the report is gathered.
        locations_by_identity: Location phrases keyed by report identity, or None when
            no fire has a location.

    Returns:
        One report entry per fire, in the input order.
    """
    return tuple(
        report_entry(
            fire,
            scores_by_identifier,
            scores_by_name,
            reference_time,
            location=(
                None
                if locations_by_identity is None
                else locations_by_identity.get(fire_identity(fire))
            ),
        )
        for fire in fires
    )


def located_entries(
    fires: typing.Iterable[peri_scribe.kml.fire_data.FireGeometry],
    scores_by_identifier: typing.Mapping[str, peri_scribe.models.FireScoreEntry],
    scores_by_name: typing.Mapping[str, peri_scribe.models.FireScoreEntry],
    reference_time: datetime.datetime,
    year_directory: pathlib.Path,
) -> tuple[FireReportEntry, ...]:
    """Return the report entries for one fire list, each carrying its location.

    The location phrases are computed from the year's major cities for exactly the fires
    in *fires*, so a fire that appears in several report lists is located once per list
    it appears in, and every gathered list carries its fires' phrases.

    Args:
        fires: The fires to describe.
        scores_by_identifier: Score entries keyed by identifier.
        scores_by_name: Score entries without identifiers, keyed by name.
        reference_time: The wall-clock time the report is gathered.
        year_directory: The year directory that holds the ``sources`` directory.

    Returns:
        One report entry per fire, in the input order.
    """
    return report_entries(
        fires,
        scores_by_identifier,
        scores_by_name,
        reference_time,
        locations_by_identity=fire_locations(
            fires,
            read_cities_layer(year_directory),
        ),
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
    new_notable_entries = located_entries(
        peri_scribe.kml.folders.new_notable_fires(
            fires,
            fire_scores,
            reference_time,
        ),
        scores_by_identifier,
        scores_by_name,
        reference_time,
        year_directory,
    )
    fast_growing_by_acres_entries = located_entries(
        peri_scribe.kml.folders.fast_growing_fires_by_acres(
            fires,
            reference_time,
        ),
        scores_by_identifier,
        scores_by_name,
        reference_time,
        year_directory,
    )
    fast_growing_by_percent_entries = located_entries(
        peri_scribe.kml.folders.fast_growing_fires_by_percent(
            fires,
            reference_time,
        ),
        scores_by_identifier,
        scores_by_name,
        reference_time,
        year_directory,
    )
    top_fire_entries = located_entries(
        peri_scribe.kml.folders.top_fires(fires, fire_scores),
        scores_by_identifier,
        scores_by_name,
        reference_time,
        year_directory,
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
