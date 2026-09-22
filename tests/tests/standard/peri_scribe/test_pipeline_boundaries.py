"""Source classification requires boundary creation before its first index read."""

from __future__ import annotations

import pathlib

import pytest

import peri_scribe.exceptions
import peri_scribe.pipeline_state
import peri_scribe.sources.administrative_boundaries
import tests.helpers.doubles.errors
import tests.helpers.doubles.peri_scribe.pipeline_boundaries


@pytest.mark.parametrize("gated", [False, True], ids=["ungated", "gated"])
def test_run_fetch_stage_creates_missing_boundary_before_indexing(
    tmp_path: pathlib.Path,
    monkeypatch: pytest.MonkeyPatch,
    *,
    gated: bool,
) -> None:
    year_directory = tmp_path / "data" / "2026"
    scenario = tests.helpers.doubles.peri_scribe.pipeline_boundaries.install(
        monkeypatch,
        year_directory,
    )
    boundary = peri_scribe.sources.administrative_boundaries.output_geopackage_path(
        year_directory,
    )
    assert not boundary.exists()

    assert tests.helpers.doubles.peri_scribe.pipeline_boundaries.run_fetch(
        year_directory,
        gated=gated,
    )

    assert scenario.indexed == [year_directory]
    assert len(scenario.borders) == 1
    assert not scenario.borders[0].is_empty
    assert peri_scribe.sources.administrative_boundaries.is_usable(boundary)


@pytest.mark.parametrize("gated", [False, True], ids=["ungated", "gated"])
def test_run_fetch_stage_preserves_retry_when_boundary_preparation_fails(
    tmp_path: pathlib.Path,
    monkeypatch: pytest.MonkeyPatch,
    *,
    gated: bool,
) -> None:
    year_directory = tmp_path / "data" / "2026"
    scenario = tests.helpers.doubles.peri_scribe.pipeline_boundaries.install(
        monkeypatch,
        year_directory,
    )
    monkeypatch.setattr(
        peri_scribe.sources.administrative_boundaries,
        "ensure_administrative_boundaries",
        tests.helpers.doubles.errors.raising_stub(
            peri_scribe.exceptions.AdministrativeBoundariesError("download failed"),
        ),
    )

    with pytest.raises(
        peri_scribe.exceptions.AdministrativeBoundariesError,
        match="download failed",
    ):
        tests.helpers.doubles.peri_scribe.pipeline_boundaries.run_fetch(
            year_directory,
            gated=gated,
        )

    assert scenario.indexed == []
    assert peri_scribe.pipeline_state.read_state(year_directory).remaining == (
        peri_scribe.pipeline_state.DERIVED_STAGES
    )
