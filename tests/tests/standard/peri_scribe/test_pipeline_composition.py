"""Publication deferral remains visible when a later invocation changes policy."""

import unittest.mock

import pytest
import time_machine

import peri_scribe.pipeline
import peri_scribe.pipeline_state
import peri_scribe.publication
import peri_scribe.sources.fetching
import tests.helpers.doubles.peri_scribe.pipeline_fetch_recovery
import tests.helpers.factories.peri_scribe.publication
import tests.helpers.peri_scribe.main_publication


@pytest.mark.parametrize("intermediate_gated", [None, False, True])
def test_run_selected_stages_ungated_retry_builds_previously_deferred_inputs(
    scenario: tests.helpers.peri_scribe.main_publication.Scenario,
    monkeypatch: pytest.MonkeyPatch,
    *,
    intermediate_gated: bool | None,
) -> None:
    threshold = tests.helpers.factories.peri_scribe.publication.THRESHOLD
    with time_machine.travel(
        tests.helpers.peri_scribe.main_publication.NOW,
        tick=False,
    ):
        peri_scribe.pipeline.run_selected_stages(
            scenario.year,
            0,
            len(peri_scribe.pipeline.PIPELINE_STAGES) - 1,
            full_fetch_interval=None,
            unconditional=False,
            publish_threshold=threshold,
        )
        assert scenario.stubs.history_calls == []
        if intermediate_gated is not None:
            peri_scribe.pipeline.run_selected_stages(
                scenario.year,
                3,
                3,
                full_fetch_interval=None,
                unconditional=False,
                publish_threshold=threshold if intermediate_gated else None,
            )
        assert peri_scribe.pipeline_state.deferred_inputs_path(scenario.year).exists()
        monkeypatch.setattr(
            peri_scribe.sources.fetching,
            "fetch_all_feeds",
            lambda *_args, **_kwargs: peri_scribe.sources.fetching.FetchResult(
                snapshot_paths=(),
                changed=False,
            ),
        )
        peri_scribe.pipeline.run_selected_stages(
            scenario.year,
            0,
            len(peri_scribe.pipeline.PIPELINE_STAGES) - 1,
            full_fetch_interval=None,
            unconditional=False,
        )
    assert scenario.stubs.history_calls == [scenario.year]
    assert not peri_scribe.pipeline_state.deferred_inputs_path(scenario.year).exists()


def test_run_gated_fetch_stage_clears_deferred_marker_when_checkpoint_covers_inputs(
    scenario: tests.helpers.peri_scribe.main_publication.Scenario,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    peri_scribe.pipeline_state.defer_inputs(scenario.year)
    inputs = tests.helpers.factories.peri_scribe.publication.collection(
        tests.helpers.factories.peri_scribe.publication.mapping(100),
    )
    monkeypatch.setattr(peri_scribe.publication, "collect", lambda _year: inputs)
    assert not peri_scribe.pipeline.run_gated_fetch_stage(
        scenario.year,
        full_fetch_interval=None,
        unconditional=False,
        threshold=tests.helpers.factories.peri_scribe.publication.THRESHOLD,
    )
    assert not peri_scribe.pipeline_state.deferred_inputs_path(scenario.year).exists()
    assert peri_scribe.pipeline_state.read_state(scenario.year).remaining == ()


def test_run_gated_fetch_stage_preserves_intent_when_collection_loses_process(
    scenario: tests.helpers.peri_scribe.main_publication.Scenario,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(
        peri_scribe.pipeline,
        "fetch_fire_sources",
        unittest.mock.Mock(
            side_effect=tests.helpers.doubles.peri_scribe.pipeline_fetch_recovery.ProcessLoss,
        ),
    )
    with pytest.raises(
        tests.helpers.doubles.peri_scribe.pipeline_fetch_recovery.ProcessLoss,
    ):
        peri_scribe.pipeline.run_gated_fetch_stage(
            scenario.year,
            full_fetch_interval=None,
            unconditional=False,
            threshold=tests.helpers.factories.peri_scribe.publication.THRESHOLD,
        )
    assert peri_scribe.pipeline_state.deferred_inputs_path(scenario.year).exists()


@pytest.mark.parametrize(
    ("operation", "pending", "deferred"),
    [
        ("require_stages", False, True),
        ("clear_deferred_inputs", True, True),
        ("fetch_fire_sources", True, False),
    ],
)
def test_run_fetch_stage_protects_deferred_inputs_across_transfer_failure(
    scenario: tests.helpers.peri_scribe.main_publication.Scenario,
    operation: str,
    *,
    pending: bool,
    deferred: bool,
) -> None:
    peri_scribe.pipeline_state.defer_inputs(scenario.year)
    with pytest.MonkeyPatch.context() as monkeypatch:
        monkeypatch.setattr(
            peri_scribe.pipeline
            if operation == "fetch_fire_sources"
            else peri_scribe.pipeline_state,
            operation,
            unittest.mock.Mock(
                side_effect=(
                    tests.helpers.doubles.peri_scribe.pipeline_fetch_recovery.ProcessLoss
                ),
            ),
        )
        with pytest.raises(
            tests.helpers.doubles.peri_scribe.pipeline_fetch_recovery.ProcessLoss,
        ):
            peri_scribe.pipeline.run_fetch_stage(
                scenario.year,
                full_fetch_interval=None,
                unconditional=False,
            )
    assert peri_scribe.pipeline_state.deferred_inputs_path(scenario.year).exists() == (
        deferred
    )
    assert peri_scribe.pipeline_state.read_state(scenario.year).remaining == (
        peri_scribe.pipeline_state.DERIVED_STAGES if pending else ()
    )
