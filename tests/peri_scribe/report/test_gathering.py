"""Tests for peri_scribe.report.gathering."""

from __future__ import annotations

import datetime
import pathlib

import geopandas
import pytest
import shapely.geometry

import peri_scribe.fires.differential
import peri_scribe.fires.files
import peri_scribe.fires.index
import peri_scribe.fires.score_files
import peri_scribe.geo.reading
import peri_scribe.kml.descriptions
import peri_scribe.kml.fire_data
import peri_scribe.kml.folders
import peri_scribe.models
import peri_scribe.report.gathering
import peri_scribe.report.locations
import peri_scribe.sources.external_sources
import tests.peri_scribe.kml.kml_helpers
from peri_scribe.units import units


def make_fire(
    name: str,
    identifier: str,
) -> peri_scribe.kml.fire_data.FireGeometry:
    """Return a described fire with the given name and identifier.

    Args:
        name: The fire's name.
        identifier: The fire's identifier.

    Returns:
        An active fire with a description carrying fixed area, containment, and
        discovery facts.
    """
    return peri_scribe.kml.fire_data.FireGeometry(
        name=name,
        status=peri_scribe.models.FireStatus.ACTIVE,
        point=None,
        perimeters=(),
        identifiers=frozenset({identifier}),
        description=peri_scribe.kml.descriptions.FireDescription(
            identifier=identifier,
            area=100.0 * units.acres,
            percent_contained=50.0,
            discovery_time=datetime.datetime(2026, 8, 1, tzinfo=datetime.UTC),
        ),
    )


def make_entry(
    name: str,
    *,
    identifier: str | None = None,
) -> peri_scribe.report.gathering.FireReportEntry:
    """Return a report entry carrying only the given identity facts.

    Args:
        name: The fire's name.
        identifier: The fire's identifier, or None.

    Returns:
        An active fire entry with no other facts set.
    """
    return peri_scribe.report.gathering.FireReportEntry(
        name=name,
        identifier=identifier,
        status=peri_scribe.models.FireStatus.ACTIVE,
        description=None,
        growth=None,
        growth_percent=None,
        score=None,
    )


def test_report_entry_captures_fire_facts(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    fire = make_fire("Bug", "2026-casnd-150541")
    monkeypatch.setattr(
        peri_scribe.kml.folders,
        "fire_growth",
        lambda _fire, _reference_time: (
            50.0 * units.acres,
            10.0 * units.percent,
        ),
    )
    monkeypatch.setattr(
        peri_scribe.kml.folders,
        "score_value_for_fire",
        lambda _fire, _by_identifier, _by_name: 400,
    )

    entry = peri_scribe.report.gathering.report_entry(
        fire,
        {},
        {},
        datetime.datetime(2026, 8, 2, tzinfo=datetime.UTC),
    )

    description = entry.description
    assert description is not None
    assert description.area is not None
    assert entry.name == "Bug"
    assert entry.identifier == "2026-casnd-150541"
    assert entry.status is peri_scribe.models.FireStatus.ACTIVE
    assert description.area.m_as("acres") == pytest.approx(100.0)
    assert description.percent_contained == pytest.approx(50.0)
    assert description.discovery_time == datetime.datetime(
        2026,
        8,
        1,
        tzinfo=datetime.UTC,
    )
    assert entry.growth is not None
    assert entry.growth_percent is not None
    assert entry.growth.m_as("acres") == pytest.approx(50.0)
    assert entry.growth_percent.m_as("percent") == pytest.approx(10.0)
    assert entry.score == pytest.approx(400)


def test_report_entry_prefers_unique_fire_identifier(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    fire = peri_scribe.kml.fire_data.FireGeometry(
        name="Bug",
        status=peri_scribe.models.FireStatus.ACTIVE,
        point=None,
        perimeters=(),
        identifiers=frozenset({
            "286b7f1d-8945-4a5d-9d81-5235c18af1fe",
            "2026-casnd-150541",
        }),
    )
    monkeypatch.setattr(
        peri_scribe.kml.folders,
        "fire_growth",
        lambda _fire, _reference_time: (None, None),
    )
    monkeypatch.setattr(
        peri_scribe.kml.folders,
        "score_value_for_fire",
        lambda _fire, _by_identifier, _by_name: None,
    )

    entry = peri_scribe.report.gathering.report_entry(
        fire,
        {},
        {},
        datetime.datetime(2026, 8, 2, tzinfo=datetime.UTC),
    )

    assert entry.identifier == "2026-casnd-150541"


def test_gather_report_assembles_each_fire_list(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    year_directory = pathlib.Path("data/2026")
    index = tests.peri_scribe.kml.kml_helpers.fire_index([
        tests.peri_scribe.kml.kml_helpers.fire_index_entry(
            "Bug",
            "active",
            identifier="id-bug",
        ),
    ])
    monkeypatch.setattr(
        peri_scribe.fires.index,
        "load_fire_index",
        lambda _directory: index,
    )
    monkeypatch.setattr(
        peri_scribe.fires.score_files,
        "load_fire_scores",
        lambda _directory: peri_scribe.models.FireScores(version="test", fires=[]),
    )
    monkeypatch.setattr(
        peri_scribe.fires.files,
        "history_geopackage_path",
        lambda _directory: pathlib.Path("/derived/full.gpkg"),
    )
    monkeypatch.setattr(
        peri_scribe.fires.differential,
        "differential_geopackage_path",
        lambda _directory: pathlib.Path("/derived/differential.gpkg"),
    )
    monkeypatch.setattr(
        peri_scribe.geo.reading,
        "read_layer",
        lambda _path, _layer_name: tests.peri_scribe.kml.kml_helpers.geometry_frame([]),
    )
    fire = make_fire("Bug", "id-bug")
    monkeypatch.setattr(
        peri_scribe.kml.fire_data,
        "fire_geometries",
        lambda *_arguments, **_keywords: [fire],
    )
    monkeypatch.setattr(
        peri_scribe.kml.folders,
        "new_notable_fires",
        lambda _fires, _scores, _reference_time: [fire],
    )
    monkeypatch.setattr(
        peri_scribe.kml.folders,
        "type_one_fires",
        lambda _fires: [fire],
    )
    monkeypatch.setattr(
        peri_scribe.kml.folders,
        "fast_growing_fires_by_acres",
        lambda _fires, _reference_time: [fire],
    )
    monkeypatch.setattr(
        peri_scribe.kml.folders,
        "fast_growing_fires_by_percent",
        lambda _fires, _reference_time: [fire],
    )
    monkeypatch.setattr(
        peri_scribe.kml.folders,
        "top_fires",
        lambda _fires, _scores: [fire],
    )

    report = peri_scribe.report.gathering.gather_report(year_directory)

    assert [entry.name for entry in report.new_notable_fires] == ["Bug"]
    assert [entry.name for entry in report.type_one_fires] == ["Bug"]
    assert [entry.name for entry in report.fastest_growing_by_acres] == ["Bug"]
    assert [entry.name for entry in report.fastest_growing_by_percent] == ["Bug"]
    assert [entry.name for entry in report.top_fires] == ["Bug"]
    assert [entry.name for entry in report.fire_details] == ["Bug"]


def test_report_details_returns_each_fire_once_sorted_by_name() -> None:
    bug = make_entry("Bug", identifier="id-bug")
    fire = make_entry("Fire", identifier="id-fire")

    details = peri_scribe.report.gathering.report_details(
        (fire, bug),
        (bug,),
        (),
    )

    assert details == (bug, fire)


def test_report_details_sorts_case_insensitively() -> None:
    alpha = make_entry("alpha")
    beta = make_entry("Beta")

    details = peri_scribe.report.gathering.report_details((beta, alpha))

    assert details == (alpha, beta)


def test_report_details_keeps_same_name_fires_distinct() -> None:
    first = make_entry("Bug", identifier="id-first")
    second = make_entry("Bug", identifier="id-second")

    details = peri_scribe.report.gathering.report_details((second, first))

    assert details == (first, second)


def test_report_details_identifies_unnamed_fire_by_name() -> None:
    bug = make_entry("Bug")

    details = peri_scribe.report.gathering.report_details((bug, bug))

    assert details == (bug,)


def test_gather_report_skips_plot_rendering(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    year_directory = pathlib.Path("data/2026")
    index = tests.peri_scribe.kml.kml_helpers.fire_index([])
    monkeypatch.setattr(
        peri_scribe.fires.index,
        "load_fire_index",
        lambda _directory: index,
    )
    monkeypatch.setattr(
        peri_scribe.fires.score_files,
        "load_fire_scores",
        lambda _directory: None,
    )
    monkeypatch.setattr(
        peri_scribe.fires.files,
        "history_geopackage_path",
        lambda _directory: pathlib.Path("/derived/full.gpkg"),
    )
    monkeypatch.setattr(
        peri_scribe.fires.differential,
        "differential_geopackage_path",
        lambda _directory: pathlib.Path("/derived/differential.gpkg"),
    )
    monkeypatch.setattr(
        peri_scribe.geo.reading,
        "read_layer",
        lambda _path, _layer_name: tests.peri_scribe.kml.kml_helpers.geometry_frame([]),
    )
    render_plots_values: list[bool] = []

    def fire_geometries(
        *_arguments: object,
        scores: peri_scribe.models.FireScores,
        render_plots: bool,
    ) -> list[peri_scribe.kml.fire_data.FireGeometry]:
        render_plots_values.append(render_plots)
        return []

    monkeypatch.setattr(
        peri_scribe.kml.fire_data,
        "fire_geometries",
        fire_geometries,
    )

    peri_scribe.report.gathering.gather_report(year_directory)

    assert render_plots_values == [False]


def test_gather_report_uses_empty_scores_when_missing(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    year_directory = pathlib.Path("data/2026")
    index = tests.peri_scribe.kml.kml_helpers.fire_index([])
    monkeypatch.setattr(
        peri_scribe.fires.index,
        "load_fire_index",
        lambda _directory: index,
    )
    monkeypatch.setattr(
        peri_scribe.fires.score_files,
        "load_fire_scores",
        lambda _directory: None,
    )
    monkeypatch.setattr(
        peri_scribe.fires.files,
        "history_geopackage_path",
        lambda _directory: pathlib.Path("/derived/full.gpkg"),
    )
    monkeypatch.setattr(
        peri_scribe.fires.differential,
        "differential_geopackage_path",
        lambda _directory: pathlib.Path("/derived/differential.gpkg"),
    )
    monkeypatch.setattr(
        peri_scribe.geo.reading,
        "read_layer",
        lambda _path, _layer_name: tests.peri_scribe.kml.kml_helpers.geometry_frame([]),
    )
    scores_values: list[peri_scribe.models.FireScores] = []

    def fire_geometries(
        *_arguments: object,
        scores: peri_scribe.models.FireScores,
        render_plots: bool,
    ) -> list[peri_scribe.kml.fire_data.FireGeometry]:
        scores_values.append(scores)
        return []

    monkeypatch.setattr(
        peri_scribe.kml.fire_data,
        "fire_geometries",
        fire_geometries,
    )

    peri_scribe.report.gathering.gather_report(year_directory)

    assert scores_values == [peri_scribe.models.FireScores(version="", fires=[])]


def located_fire(
    name: str,
    identifier: str,
) -> peri_scribe.kml.fire_data.FireGeometry:
    """Return an active fire with one mapped perimeter.

    Args:
        name: The fire's name.
        identifier: The fire's identifier.

    Returns:
        A fire whose latest perimeter is a non-empty polygon, so its location can be
        measured from an interior.
    """
    return peri_scribe.kml.fire_data.FireGeometry(
        name=name,
        status=peri_scribe.models.FireStatus.ACTIVE,
        point=None,
        perimeters=(
            peri_scribe.kml.fire_data.Perimeter(
                geometry=shapely.geometry.Point(-122.6750, 45.5051).buffer(0.1),
                observation_time=None,
            ),
        ),
        identifiers=frozenset({identifier}),
        description=None,
    )


def test_report_entry_captures_location() -> None:
    fire = make_fire("Bug", "2026-casnd-150541")

    entry = peri_scribe.report.gathering.report_entry(
        fire,
        {},
        {},
        datetime.datetime(2026, 8, 2, tzinfo=datetime.UTC),
        location="15 mi ESE of Portland, OR",
    )

    assert entry.location == "15 mi ESE of Portland, OR"


def test_fire_identity_prefers_canonical_identifier() -> None:
    fire = located_fire("Bug", "2026-casnd-150541")

    assert peri_scribe.report.gathering.fire_identity(fire) == "2026-casnd-150541"


def test_fire_identity_uses_name_without_identifier() -> None:
    fire = peri_scribe.kml.fire_data.FireGeometry(
        name="Bug",
        status=peri_scribe.models.FireStatus.ACTIVE,
        point=None,
        perimeters=(),
    )

    assert peri_scribe.report.gathering.fire_identity(fire) == "Bug"


def test_fire_location_formats_nearest_city_phrase(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    fire = located_fire("Bug", "2026-casnd-150541")
    nearest = peri_scribe.report.locations.NearestCity(
        name="Portland",
        state_abbreviation="OR",
        distance=14.6 * units.miles,
        bearing=112.5 * units.degrees,
    )
    monkeypatch.setattr(
        peri_scribe.report.locations,
        "nearest_city",
        lambda _interior, _cities: nearest,
    )

    location = peri_scribe.report.gathering.fire_location(
        fire,
        geopandas.GeoDataFrame(),
    )

    assert location == "15 mi ESE of Portland, OR"


def test_fire_location_returns_none_without_geometry() -> None:
    fire = make_fire("Bug", "2026-casnd-150541")

    assert (
        peri_scribe.report.gathering.fire_location(
            fire,
            geopandas.GeoDataFrame(),
        )
        is None
    )


def test_fire_location_returns_none_with_empty_perimeter() -> None:
    fire = peri_scribe.kml.fire_data.FireGeometry(
        name="Bug",
        status=peri_scribe.models.FireStatus.ACTIVE,
        point=None,
        perimeters=(
            peri_scribe.kml.fire_data.Perimeter(
                geometry=shapely.geometry.Polygon(),
                observation_time=None,
            ),
        ),
    )

    assert (
        peri_scribe.report.gathering.fire_location(
            fire,
            geopandas.GeoDataFrame(),
        )
        is None
    )


def test_fire_location_returns_none_without_cities() -> None:
    fire = located_fire("Bug", "2026-casnd-150541")

    assert (
        peri_scribe.report.gathering.fire_location(
            fire,
            geopandas.GeoDataFrame(),
        )
        is None
    )


def test_fire_location_measures_from_point_without_perimeter(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    point = shapely.geometry.Point(-122.6750, 45.5051)
    fire = peri_scribe.kml.fire_data.FireGeometry(
        name="Bug",
        status=peri_scribe.models.FireStatus.ACTIVE,
        point=point,
        perimeters=(),
        identifiers=frozenset({"2026-casnd-150541"}),
    )
    measured: list[shapely.Geometry] = []

    def nearest_city(
        geometry: shapely.Geometry,
        _cities: geopandas.GeoDataFrame,
    ) -> peri_scribe.report.locations.NearestCity:
        measured.append(geometry)
        return peri_scribe.report.locations.NearestCity(
            name="Portland",
            state_abbreviation="OR",
            distance=14.6 * units.miles,
            bearing=112.5 * units.degrees,
        )

    monkeypatch.setattr(
        peri_scribe.report.locations,
        "nearest_city",
        nearest_city,
    )

    location = peri_scribe.report.gathering.fire_location(
        fire,
        geopandas.GeoDataFrame(),
    )

    assert measured == [point]
    assert location == "15 mi ESE of Portland, OR"


def test_fire_location_falls_back_to_point_for_empty_perimeter(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    point = shapely.geometry.Point(-122.6750, 45.5051)
    fire = peri_scribe.kml.fire_data.FireGeometry(
        name="Bug",
        status=peri_scribe.models.FireStatus.ACTIVE,
        point=point,
        perimeters=(
            peri_scribe.kml.fire_data.Perimeter(
                geometry=shapely.geometry.Polygon(),
                observation_time=None,
            ),
        ),
        identifiers=frozenset({"2026-casnd-150541"}),
    )
    measured: list[shapely.Geometry] = []

    def nearest_city(
        geometry: shapely.Geometry,
        _cities: geopandas.GeoDataFrame,
    ) -> peri_scribe.report.locations.NearestCity:
        measured.append(geometry)
        return peri_scribe.report.locations.NearestCity(
            name="Portland",
            state_abbreviation="OR",
            distance=14.6 * units.miles,
            bearing=112.5 * units.degrees,
        )

    monkeypatch.setattr(
        peri_scribe.report.locations,
        "nearest_city",
        nearest_city,
    )

    location = peri_scribe.report.gathering.fire_location(
        fire,
        geopandas.GeoDataFrame(),
    )

    assert measured == [point]
    assert location == "15 mi ESE of Portland, OR"


def test_fire_location_measures_point_to_nearest_city() -> None:
    point = shapely.geometry.Point(-122.6750, 45.5051)
    fire = peri_scribe.kml.fire_data.FireGeometry(
        name="Bug",
        status=peri_scribe.models.FireStatus.ACTIVE,
        point=point,
        perimeters=(),
        identifiers=frozenset({"2026-casnd-150541"}),
    )
    cities = geopandas.GeoDataFrame(
        {
            "NAME": ["Faraway", "Portland"],
            "STATE_ABBR": ["OR", "OR"],
            "geometry": [
                shapely.geometry.Point(-123.5, 45.5051),
                point,
            ],
        },
        crs="EPSG:4326",
    )

    location = peri_scribe.report.gathering.fire_location(fire, cities)

    assert location == "0 mi of Portland, OR"


def test_fire_locations_maps_each_located_fire_once(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    located = located_fire("Bug", "2026-casnd-150541")
    without_perimeter = make_fire("Fire", "2026-casnd-150542")
    nearest = peri_scribe.report.locations.NearestCity(
        name="Portland",
        state_abbreviation="OR",
        distance=14.6 * units.miles,
        bearing=112.5 * units.degrees,
    )
    monkeypatch.setattr(
        peri_scribe.report.locations,
        "nearest_city",
        lambda _interior, _cities: nearest,
    )

    locations = peri_scribe.report.gathering.fire_locations(
        (located, located, without_perimeter),
        geopandas.GeoDataFrame(),
    )

    assert locations == {"2026-casnd-150541": "15 mi ESE of Portland, OR"}


def test_located_entries_attach_location_phrases(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    fire = located_fire("Bug", "2026-casnd-150541")
    nearest = peri_scribe.report.locations.NearestCity(
        name="Portland",
        state_abbreviation="OR",
        distance=14.6 * units.miles,
        bearing=112.5 * units.degrees,
    )
    monkeypatch.setattr(
        peri_scribe.report.locations,
        "nearest_city",
        lambda _interior, _cities: nearest,
    )
    monkeypatch.setattr(
        peri_scribe.report.gathering,
        "read_cities_layer",
        lambda _year_directory: geopandas.GeoDataFrame(),
    )

    entries = peri_scribe.report.gathering.located_entries(
        (fire,),
        {},
        {},
        datetime.datetime(2026, 8, 2, tzinfo=datetime.UTC),
        pathlib.Path("data/2026"),
    )

    assert entries[0].location == "15 mi ESE of Portland, OR"


def test_read_cities_layer_reads_stored_layer(
    tmp_path: pathlib.Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    year_directory = tmp_path / "2026"
    path = peri_scribe.sources.external_sources.output_path(
        year_directory,
        peri_scribe.sources.external_sources.MAJOR_CITIES_SOURCE,
    )
    path.parent.mkdir(parents=True)
    path.touch()
    calls: list[tuple[pathlib.Path, str]] = []

    def read_layer(
        path: pathlib.Path,
        layer_name: str,
    ) -> geopandas.GeoDataFrame:
        calls.append((path, layer_name))
        return geopandas.GeoDataFrame()

    monkeypatch.setattr(peri_scribe.geo.reading, "read_layer", read_layer)

    frame = peri_scribe.report.gathering.read_cities_layer(year_directory)

    assert calls == [(path, "major_cities")]
    assert frame.empty


def test_read_cities_layer_returns_empty_frame_when_absent(
    tmp_path: pathlib.Path,
) -> None:
    frame = peri_scribe.report.gathering.read_cities_layer(tmp_path / "2026")

    assert frame.empty
