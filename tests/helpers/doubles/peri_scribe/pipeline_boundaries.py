"""Exercise boundary readiness through real GeoPackage reads during indexing."""

from __future__ import annotations

import dataclasses
import datetime
import pathlib
import typing

import peri_scribe.fires.index
import peri_scribe.logging
import peri_scribe.pipeline
import peri_scribe.pipeline_stages
import peri_scribe.publication
import peri_scribe.sources.administrative_boundaries
import peri_scribe.sources.fetching
import tests.helpers.doubles.peri_scribe.sources.administrative_boundaries
import tests.helpers.factories.peri_scribe.sources.administrative_boundaries
from measurement_units import units


if typing.TYPE_CHECKING:
    import pytest
    import shapely


@dataclasses.dataclass(frozen=True, kw_only=True)
class BoundaryScenario:
    """Retain observable indexing attempts and the actual geometry they could read."""

    year_directory: pathlib.Path
    indexed: list[pathlib.Path] = dataclasses.field(default_factory=list)
    borders: list[shapely.Geometry] = dataclasses.field(default_factory=list)

    def index(self, year_directory: pathlib.Path) -> None:
        """Expose a missing boundary with the same reader used by classification.

        Args:
            year_directory: The isolated data directory being indexed.
        """
        self.indexed.append(year_directory)
        self.borders.append(
            peri_scribe.sources.administrative_boundaries.load_border_geometry(
                year_directory,
            ),
        )

    def fetch(
        self,
        _base_directory: pathlib.Path,
        *,
        year: int,
        build_index: bool = True,
        **_kwargs: object,
    ) -> peri_scribe.sources.fetching.FetchResult:
        """Preserve whether feed collection owns or defers source indexing.

        Args:
            _base_directory: The source collection root.
            year: The requested collection year.
            build_index: Whether collection should also index its saved sources.
            _kwargs: Additional collection options unrelated to boundary readiness.

        Returns:
            A changed collection without any external network access.
        """
        assert str(year) == self.year_directory.name
        if build_index:
            peri_scribe.fires.index.index_fire_sources(self.year_directory)
        return peri_scribe.sources.fetching.FetchResult(snapshot_paths=(), changed=True)


def install(
    monkeypatch: pytest.MonkeyPatch,
    year_directory: pathlib.Path,
) -> BoundaryScenario:
    """Keep dependency creation and consumption real while isolating collection.

    Args:
        monkeypatch: Restores the replaced application dependencies after each test.
        year_directory: The isolated year's data directory.

    Returns:
        Observable boundary loading and indexing state.
    """
    scenario = BoundaryScenario(year_directory=year_directory)
    monkeypatch.setattr(
        peri_scribe.sources.administrative_boundaries.arcgis.gis,
        "GIS",
        object,
    )
    state_set = (
        tests.helpers.factories.peri_scribe.sources.administrative_boundaries
    ).polygon_feature_set(
        [
            tests.helpers.factories.peri_scribe.sources.administrative_boundaries.CALIFORNIA,
            tests.helpers.factories.peri_scribe.sources.administrative_boundaries.ARIZONA,
            tests.helpers.factories.peri_scribe.sources.administrative_boundaries.NEVADA,
            tests.helpers.factories.peri_scribe.sources.administrative_boundaries.OREGON,
        ],
        ["California", "Arizona", "Nevada", "Oregon"],
        ["CA", "AZ", "NV", "OR"],
    )
    layer_factory = (
        tests.helpers.doubles.peri_scribe.sources.administrative_boundaries
    ).make_layer_factory(state_set=state_set)
    monkeypatch.setattr(
        peri_scribe.sources.administrative_boundaries.arcgis.features,
        "FeatureLayer",
        layer_factory,
    )
    monkeypatch.setattr(peri_scribe.fires.index, "index_fire_sources", scenario.index)
    monkeypatch.setattr(peri_scribe.sources.fetching, "fetch_all_feeds", scenario.fetch)
    monkeypatch.setattr(
        peri_scribe.pipeline,
        "fetch_external_source",
        lambda *_args: None,
    )
    monkeypatch.setattr(
        peri_scribe.pipeline,
        "publication_decision",
        lambda *_args: peri_scribe.publication.Decision(
            proceed=True,
            reason=peri_scribe.publication.Reason.NO_PUBLICATION,
        ),
    )
    return scenario


def run_fetch(year_directory: pathlib.Path, *, gated: bool) -> bool:
    """Exercise either pipeline fetch path with the same boundary dependency.

    Args:
        year_directory: The isolated year's data directory.
        gated: Whether publication acceptance defers source indexing.

    Returns:
        Whether the fetch permits downstream generation.
    """
    threshold = (
        peri_scribe.publication.Threshold(
            area=25 * units.acres,
            interval=datetime.timedelta(minutes=5),
        )
        if gated
        else None
    )
    with peri_scribe.logging.log_phase(peri_scribe.pipeline_stages.Stage.FETCH):
        return peri_scribe.pipeline.run_fetch_stage(
            year_directory,
            full_fetch_interval=None,
            unconditional=False,
            publish_threshold=threshold,
        )
