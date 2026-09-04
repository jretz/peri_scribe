"""Tests for peri_scribe.report.gathering."""

from __future__ import annotations

import datetime
import pathlib

import pytest

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
import tests.peri_scribe.kml.kml_helpers


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
            area_in_acres=100.0,
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
        area_in_acres=None,
        percent_contained=None,
        discovery_time=None,
        growth_in_acres=None,
        growth_in_percent=None,
        score=None,
    )


def test_report_entry_captures_fire_facts(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    fire = make_fire("Bug", "2026-casnd-150541")
    monkeypatch.setattr(
        peri_scribe.kml.folders,
        "fire_growth",
        lambda _fire, _reference_time: (50.0, 10.0),
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

    assert entry.name == "Bug"
    assert entry.identifier == "2026-casnd-150541"
    assert entry.status is peri_scribe.models.FireStatus.ACTIVE
    assert entry.area_in_acres == pytest.approx(100.0)
    assert entry.percent_contained == pytest.approx(50.0)
    assert entry.discovery_time == datetime.datetime(
        2026,
        8,
        1,
        tzinfo=datetime.UTC,
    )
    assert entry.growth_in_acres == pytest.approx(50.0)
    assert entry.growth_in_percent == pytest.approx(10.0)
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
