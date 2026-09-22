"""Output stages can rebuild a missing index within the registered phase tree."""

from __future__ import annotations

import pathlib

import pytest
import structlog.testing

import peri_scribe.fires.index
import peri_scribe.logging
import peri_scribe.phases
import peri_scribe.pipeline_stages
import peri_scribe.sources.snapshots


@pytest.mark.parametrize(
    "stage",
    [peri_scribe.pipeline_stages.Stage.KMZ, peri_scribe.pipeline_stages.Stage.REPORTS],
)
def test_load_fire_index_builds_missing_index_within_output_stage(
    tmp_path: pathlib.Path,
    stage: peri_scribe.pipeline_stages.Stage,
) -> None:
    index_path = peri_scribe.sources.snapshots.fire_index_path(tmp_path)
    assert not index_path.exists()

    with (
        structlog.testing.capture_logs() as events,
        peri_scribe.logging.log_phase(stage),
    ):
        index = peri_scribe.fires.index.load_fire_index(tmp_path)

    assert index.fires == []
    assert index_path.is_file()
    recorded = {
        entry["phase_path"] for entry in events if entry["event"] == "Starting phase"
    }
    assert f"{stage}.source-index" in recorded
    planned = {
        ".".join(segment.phase for segment in path)
        for path in peri_scribe.phases.planned_paths(
            peri_scribe.phases.Branches(),
            gated=False,
            roots=(stage,),
        )
    }
    assert recorded <= planned
