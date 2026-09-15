"""Fixtures for the fire tests."""

from __future__ import annotations

import pathlib
import typing

import geopandas
import pytest
import shapely
import shapely.geometry

import peri_scribe.fires.derived_layers
import peri_scribe.fires.files
import peri_scribe.fires.scores
import peri_scribe.fires.sources
import peri_scribe.geo.package
import peri_scribe.models
import peri_scribe.output
import peri_scribe.sources.external_data
import peri_scribe.sources.feed_types
import tests.factories
import tests.peri_scribe.fires.fire_helpers


@pytest.fixture
def score_fires_stubs(
    monkeypatch: pytest.MonkeyPatch,
) -> typing.Callable[..., tests.peri_scribe.fires.fire_helpers.ScoreFiresStubs]:
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
    ) -> tests.peri_scribe.fires.fire_helpers.ScoreFiresStubs:
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
            return tests.factories.empty_frame()

        monkeypatch.setattr(
            peri_scribe.fires.derived_layers,
            "read_layer_if_present",
            read_layer_if_present,
        )
        monkeypatch.setattr(
            peri_scribe.fires.derived_layers,
            "read_incident_layer",
            lambda _path: tests.factories.empty_frame(),
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


@pytest.fixture
def history_inputs(
    tmp_path: pathlib.Path,
    monkeypatch: pytest.MonkeyPatch,
) -> list[peri_scribe.fires.sources.ReadFireSources]:
    """Exercise real derivation and file I/O with isolated source-reader inputs.

    Args:
        tmp_path: The isolated year directory for source paths and derived output.
        monkeypatch: The fixture used to replace the source reader.

    Returns:
        A replaceable source read for two independently changing fires.
    """
    feed = "CA_Perimeters_NIFC_FIRIS_public_view_0"
    rows = tuple(
        peri_scribe.geo.package.FireRowRecord(
            record=tests.factories.fire_record(
                name,
                tests.factories.ACTIVE,
                {name.casefold()},
                geometry=geometry,
                observed_at=tests.factories.utc(2026, 9, 1 + index, 0),
            ),
            source_name=feed,
            object_id=index,
            attributes={
                "area_acres": 100.0,
                "attr_ModifiedOnDateTime_dt": tests.factories.utc(
                    2026,
                    9,
                    1 + index,
                    0,
                ),
                "attr_IncidentSize": 100.0,
                "attr_EstimatedCostToDate": 1000.0,
            },
        )
        for index, (name, geometry) in enumerate([
            ("First", shapely.box(-120, 40, -119.99, 40.01)),
            ("Second", shapely.box(-121, 40, -120.99, 40.01)),
            ("First", shapely.box(-120, 40, -119.98, 40.02)),
        ])
    )
    inputs = [
        peri_scribe.fires.sources.ReadFireSources(
            rows=rows,
            paths=tuple(
                tmp_path / "sources" / feed / "000___" / f"{index:06d},lastEdit=1.gpkg"
                for index in range(len(rows))
            ),
            memberships=(),
        ),
    ]
    monkeypatch.setattr(
        peri_scribe.fires.sources,
        "read_fire_sources",
        lambda _directory: inputs[0],
    )
    return inputs


@pytest.fixture
def incident_sources(
    tmp_path: pathlib.Path,
) -> peri_scribe.fires.sources.ReadFireSources:
    """Expose report changes that a geometry-only history would discard.

    Args:
        tmp_path: The isolated base for synthetic source provenance paths.

    Returns:
        Two snapshots with identical polygon evidence and different incident costs and
        modification times; no snapshot files need to be written.
    """
    feed = "WFIGS_Interagency_Perimeters_Current_0"
    rows = tuple(
        peri_scribe.geo.package.FireRowRecord(
            record=tests.factories.fire_record(
                "Example",
                tests.factories.ACTIVE,
                {"example"},
                geometry=tests.factories.square(0.01),
                observed_at=tests.factories.utc(2026, 9, 1, 0),
            ),
            source_name=feed,
            object_id=1,
            attributes={
                "attr_IncidentSize": 100,
                "attr_EstimatedCostToDate": day * 1000,
                "attr_ModifiedOnDateTime_dt": tests.factories.utc(2026, 9, day, 0),
            },
        )
        for day in (2, 3)
    )
    return peri_scribe.fires.sources.ReadFireSources(
        rows=rows,
        paths=tuple(
            tmp_path / feed / "000___" / f"{index:06d},lastEdit=1.gpkg"
            for index in range(2)
        ),
        memberships=(),
    )


@pytest.fixture
def cached_layers() -> list[peri_scribe.models.LayerData]:
    """Supply an isolated cache payload.

    Returns:
        Small independent histories with stable derivation keys.
    """
    return [
        peri_scribe.models.LayerData(
            name="perimeters",
            dataframe=geopandas.GeoDataFrame(
                {"derivation_key": ["first", "second"], "revision": [1, 2]},
                geometry=[shapely.box(0, 0, 1, 1), shapely.box(2, 2, 3, 3)],
                crs=4326,
            ),
        ),
    ]


@pytest.fixture
def source_rows() -> peri_scribe.fires.sources.ReadFireSources:
    """Supply observations whose dependencies can change independently.

    Returns:
        Repeated shapes and a missing geometry under one fire identity.
    """
    geometry = shapely.box(0, 0, 1, 1)
    return peri_scribe.fires.sources.ReadFireSources(
        rows=tuple(
            peri_scribe.geo.package.FireRowRecord(
                record=tests.factories.fire_record(
                    "Example",
                    tests.factories.ACTIVE,
                    {"example"},
                    geometry=shape,
                ),
                source_name="CA_Perimeters_NIFC_FIRIS_public_view_0",
                object_id=1,
                attributes={"revision": index},
            )
            for index, shape in enumerate([geometry, geometry, None])
        ),
        paths=tuple(
            pathlib.Path(f"sources/feed/00000{index},lastEdit=1.gpkg")
            for index in range(3)
        ),
        memberships=(),
    )


@pytest.fixture
def repeated_geometry_sources(
    tmp_path: pathlib.Path,
    configured_feeds: list[peri_scribe.sources.feed_types.Feed],
) -> pathlib.Path:
    """Provide separate observations retaining the same fire footprint.

    Args:
        tmp_path: Isolated directory for this test's files.
        configured_feeds: Feeds with controlled name and status columns.

    Returns:
        The isolated source directory containing both observations.
    """
    directory = tmp_path / "sources"
    feed = configured_feeds[0]
    for serial, name in enumerate(["First", "Second"]):
        path = directory / feed.name / "000___" / f"{serial:06d},lastEdit=0.gpkg"
        path.parent.mkdir(parents=True, exist_ok=True)
        frame = tests.factories.geo_frame(
            {
                "incident_name": [name],
                "displayStatus": ["Active"],
                "revision": [serial],
            },
            [shapely.geometry.Point(1, 2)],
        )
        frame.to_file(path, layer=feed.name)
    return directory
