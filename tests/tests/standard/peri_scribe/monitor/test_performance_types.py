"""Performance groups distinguish the work performed by invocations of one command."""

import pytest

import peri_scribe.monitor.model
import peri_scribe.monitor.performance_types
import peri_scribe.phases
import tests.helpers.factories.peri_scribe.monitor.events


@pytest.mark.parametrize(
    ("options", "selected", "executed", "expected"),
    [
        (None, None, (), "run"),
        ({}, [], (), "run"),
        ({"full_fetch_interval": "1h"}, None, (), "run"),
        ({"list_stages": True}, None, (), "List stages"),
        ({"only_stage": "fetch"}, None, (), "Fetch only"),
        ({"to_stage": "fetch"}, None, (), "Fetch only"),
        ({}, ["fetch"], ("fetch",), "Fetch only"),
        ({}, None, ("fetch",), "Fetch only"),
        ({}, None, ("fetch", "geography"), "Conditional build"),
        ({"unconditional": True}, None, ("geography",), "Unconditional build"),
        ({"unconditional": True}, None, (), "Unconditional build"),
        ({"unconditional": False}, None, ("geography",), "Conditional build"),
        ({"unconditional": "true"}, None, (), "run"),
        ({"only_stage": "kmz"}, None, ("kmz",), "Conditional build · kmz only"),
        (
            {"from_stage": "geography", "to_stage": "kmz", "unconditional": True},
            None,
            ("geography", "score", "kmz"),
            "Unconditional build · geography to kmz",
        ),
        (
            {"from_stage": "fetch", "to_stage": "reports"},
            None,
            ("fetch", "geography", "score", "kmz", "reports"),
            "Conditional build",
        ),
        (
            {"from_stage": "geography"},
            None,
            ("geography", "score", "kmz", "reports"),
            "Conditional build · geography to reports",
        ),
        ({"only_stage": "invalid"}, None, (), "run"),
        ({"from_stage": "invalid"}, None, (), "run"),
        ({"to_stage": "invalid"}, None, (), "run"),
        ({"from_stage": ["geography"]}, None, (), "run"),
        ({"to_stage": {}}, None, (), "run"),
        ({"from_stage": "reports", "to_stage": "fetch"}, None, (), "run"),
        ({}, ["invalid"], (), "run"),
        ({}, [None], (), "run"),
        (
            {"only_stage": "fetch"},
            ["geography"],
            ("geography",),
            "Conditional build · geography only",
        ),
    ],
)
def test_run_type_distinguishes_command_modes_and_partial_stage_selections(
    options: object,
    selected: object,
    executed: tuple[str, ...],
    expected: str,
) -> None:
    run = tests.helpers.factories.peri_scribe.monitor.events.run(
        tests.helpers.factories.peri_scribe.monitor.events.record(
            "Starting command",
            command="run",
            parameters=options,
        ),
        tests.helpers.factories.peri_scribe.monitor.events.record(
            "Planned phases",
            stages=selected,
        ),
        *(
            tests.helpers.factories.peri_scribe.monitor.events.record(
                "Finished phase",
                path=(peri_scribe.phases.Segment(phase=stage),),
                status="completed",
            )
            for stage in executed
        ),
        tests.helpers.factories.peri_scribe.monitor.events.record(
            "Finished command",
            status="completed",
        ),
    )
    assert peri_scribe.monitor.performance_types.run_type(run) == expected


@pytest.mark.parametrize(
    ("message", "fields", "expected"),
    [
        (
            "Another run owns this year; skipping invocation",
            {},
            "Skipped · another run active",
        ),
        ("Publication gate skipped", {}, "Fetch only · publication deferred"),
        ("Skipped phases", {"phases": ["geography"]}, "Fetch only · unchanged"),
        ("Skipped phases", {"phases": ["deferred-fetch"]}, "Fetch only"),
        ("Skipped phases", {"phases": [None, {}]}, "Fetch only"),
        ("Skipped phases", {"phases": None}, "Fetch only"),
    ],
)
def test_run_type_separates_fast_collection_and_skipped_invocations(
    message: str,
    fields: dict[str, object],
    expected: str,
) -> None:
    run = tests.helpers.factories.peri_scribe.monitor.events.run(
        tests.helpers.factories.peri_scribe.monitor.events.record(
            "Starting command",
            command="run",
        ),
        tests.helpers.factories.peri_scribe.monitor.events.record(
            "Finished phase",
            path=(peri_scribe.phases.Segment(phase="fetch"),),
            status="completed",
        ),
        tests.helpers.factories.peri_scribe.monitor.events.record(message) | fields,
    )
    assert peri_scribe.monitor.performance_types.run_type(run) == expected


@pytest.mark.parametrize("unconditional", [False, True])
def test_run_type_uses_recorded_rebuild_requirement_when_command_options_are_missing(
    *,
    unconditional: bool,
) -> None:
    run = tests.helpers.factories.peri_scribe.monitor.events.run(
        tests.helpers.factories.peri_scribe.monitor.events.record(
            "Starting command",
            command="run",
        ),
        tests.helpers.factories.peri_scribe.monitor.events.record(
            "Finished phase",
            path=(peri_scribe.phases.Segment(phase="reports"),),
            status="completed",
        ),
        tests.helpers.factories.peri_scribe.monitor.events.record(
            "Required rebuild completed",
            unconditional=unconditional,
        ),
    )
    assert peri_scribe.monitor.performance_types.run_type(run) == (
        "Unconditional build" if unconditional else "Conditional build"
    )


def test_run_type_preserves_other_command_names() -> None:
    run = tests.helpers.factories.peri_scribe.monitor.events.run(
        tests.helpers.factories.peri_scribe.monitor.events.record(
            "Starting command",
            command="validate-sources",
        ),
    )
    assert peri_scribe.monitor.performance_types.run_type(run) == "validate-sources"


def test_parameters_ignores_phase_metadata() -> None:
    run = tests.helpers.factories.peri_scribe.monitor.events.run(
        tests.helpers.factories.peri_scribe.monitor.events.record(
            "Starting command",
            command="run",
            parameters={"unconditional": True},
        ),
        tests.helpers.factories.peri_scribe.monitor.events.record(
            "Starting phase",
            parameters={"unconditional": False},
        ),
    )
    assert peri_scribe.monitor.performance_types.parameters(
        peri_scribe.monitor.model.evidence(run),
    ) == {"unconditional": True}
