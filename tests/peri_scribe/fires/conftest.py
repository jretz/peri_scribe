"""Fixtures for the fire tests."""

from __future__ import annotations

import pathlib
import typing

import pytest

import peri_scribe.fires.derived_layers
import peri_scribe.fires.files
import peri_scribe.fires.scores
import peri_scribe.output
import peri_scribe.sources.external_sources
import tests.factories
import tests.peri_scribe.fires.fire_helpers


if typing.TYPE_CHECKING:
    import geopandas


@pytest.fixture
def score_fires_stubs(
    monkeypatch: pytest.MonkeyPatch,
) -> typing.Callable[..., tests.peri_scribe.fires.fire_helpers.ScoreFiresStubs]:
    """Install the history, external-source, and output stubs scoring needs.

    Returns:
        A callable taking the history frames to serve and how external data resolves,
        and returning the recorded writes.
    """

    def install(
        *,
        perimeters: geopandas.GeoDataFrame | None = None,
        points: geopandas.GeoDataFrame | None = None,
        output_path: typing.Callable[..., pathlib.Path] | None = None,
        stub_latest_snapshot_layer: bool = True,
    ) -> tests.peri_scribe.fires.fire_helpers.ScoreFiresStubs:
        def read_layer_if_present(
            _path: pathlib.Path,
            layer_name: str,
        ) -> geopandas.GeoDataFrame:
            if (
                layer_name == peri_scribe.fires.files.PERIMETER_LAYER_NAME
                and perimeters is not None
            ):
                return perimeters
            if (
                layer_name == peri_scribe.fires.files.POINT_LAYER_NAME
                and points is not None
            ):
                return points
            return tests.factories.empty_frame()

        monkeypatch.setattr(
            peri_scribe.fires.derived_layers,
            "read_layer_if_present",
            read_layer_if_present,
        )
        monkeypatch.setattr(
            peri_scribe.sources.external_sources,
            "output_path",
            output_path
            or (
                lambda _year_directory, _source: pathlib.Path(
                    "/missing/buildings.sqlite",
                )
            ),
        )
        if stub_latest_snapshot_layer:
            monkeypatch.setattr(
                peri_scribe.fires.scores,
                "latest_snapshot_layer",
                lambda _year_directory, _source: None,
            )
        monkeypatch.setattr(
            pathlib.Path,
            "mkdir",
            lambda *_arguments, **_keywords: None,
        )
        stubs = tests.peri_scribe.fires.fire_helpers.ScoreFiresStubs(
            writes=[],
            ccdf_writes=[],
        )
        monkeypatch.setattr(
            peri_scribe.output,
            "write_document",
            lambda path, document: stubs.writes.append((path, document)),
        )
        monkeypatch.setattr(
            peri_scribe.output,
            "write_fire_scores_ccdf",
            lambda path, document: stubs.ccdf_writes.append((path, document)),
        )
        return stubs

    return install
