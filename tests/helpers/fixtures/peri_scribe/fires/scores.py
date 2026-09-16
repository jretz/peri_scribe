"""Isolate scores tests with explicit fixtures."""

from __future__ import annotations

import pathlib
import typing

import pytest

import peri_scribe.fires.derived_layers
import peri_scribe.fires.files
import peri_scribe.fires.scores
import peri_scribe.output
import peri_scribe.sources.external_data
import tests.helpers.doubles.peri_scribe.fires.scores
import tests.helpers.factories.geography


if typing.TYPE_CHECKING:
    import geopandas


@pytest.fixture
def score_fires_stubs(
    monkeypatch: pytest.MonkeyPatch,
) -> typing.Callable[
    ...,
    tests.helpers.doubles.peri_scribe.fires.scores.ScoreFiresStubs,
]:
    """Install the history, external-source, and output stubs scoring needs.

    Args:
        monkeypatch: Replace dependencies and restore them after the test.

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
    ) -> tests.helpers.doubles.peri_scribe.fires.scores.ScoreFiresStubs:
        """Install scoring inputs and capture generated score documents.

        Args:
            perimeters: Perimeter observations supplied to scoring, or None for an empty
                layer.
            points: Point observations supplied to scoring, or None for an empty layer.
            output_path: Optional replacement for external-source output-path
                resolution.
            stub_latest_snapshot_layer: Whether to make the latest external snapshot
                unavailable.

        Returns:
            The captured score and complementary-distribution document writes.
        """

        def read_layer_if_present(
            _path: pathlib.Path,
            layer_name: str,
        ) -> geopandas.GeoDataFrame:
            """Serve the configured scoring layer without reading a GeoPackage.

            Args:
                _path: File path accepted for compatibility; the configured stub outcome
                    is used.
                layer_name: Name of the layer to select within the GeoPackage.

            Returns:
                The configured perimeter or point layer, or an empty dataframe.
            """
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
            return tests.helpers.factories.geography.empty_frame()

        monkeypatch.setattr(
            peri_scribe.fires.derived_layers,
            "read_layer_if_present",
            read_layer_if_present,
        )
        monkeypatch.setattr(
            peri_scribe.fires.derived_layers,
            "read_incident_layer",
            lambda _path: tests.helpers.factories.geography.empty_frame(),
        )
        monkeypatch.setattr(
            peri_scribe.sources.external_data,
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
            lambda *_args, **_kwargs: None,
        )
        stubs = tests.helpers.doubles.peri_scribe.fires.scores.ScoreFiresStubs(
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
