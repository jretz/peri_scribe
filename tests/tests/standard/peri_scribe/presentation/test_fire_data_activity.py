"""Activity adapters and assessment-time cache boundaries for shared summaries."""

import dataclasses
import datetime
import math

import pytest
import time_machine

import peri_scribe.execution
import peri_scribe.models
import peri_scribe.presentation.fire_data
import tests.helpers.factories.peri_scribe.fires.activity
import tests.helpers.factories.peri_scribe.kml.parsing
import tests.helpers.factories.peri_scribe.presentation.fire_data


@pytest.mark.parametrize(
    ("reported", "mapped", "expected"),
    [
        ([(-8, 4_000), (-4, 4_028)], [], peri_scribe.models.FireStatus.ACTIVE),
        ([], [(-8, 4_000), (-4, 4_028)], peri_scribe.models.FireStatus.ACTIVE),
        ([(-8, 4_000)], [(-8, 6_000)], peri_scribe.models.FireStatus.HOLDING),
        ([], [], peri_scribe.models.FireStatus.ACTIVE),
        (
            [],
            [(-8, 4_000), (-8, 3_000), (-4, 4_004)],
            peri_scribe.models.FireStatus.HOLDING,
        ),
        (
            [],
            [(-8, math.nan), (-8, 4_000), (-4, 4_004)],
            peri_scribe.models.FireStatus.HOLDING,
        ),
        (
            [],
            [(-8, -1), (-8, 4_000), (1, 8_000)],
            peri_scribe.models.FireStatus.HOLDING,
        ),
    ],
)
def test_pending_activity_keeps_streams_separate_and_uses_full_mapping_ties(
    reported: list[tuple[float, float]],
    mapped: list[tuple[float, float]],
    expected: peri_scribe.models.FireStatus,
) -> None:
    fire = tests.helpers.factories.peri_scribe.presentation.fire_data.pending_activity(
        reported,
        mapped,
    )
    assert (
        peri_scribe.presentation.fire_data.pending_activity(
            fire,
            tests.helpers.factories.peri_scribe.fires.activity.REFERENCE_TIME,
        )
        is expected
    )


def test_pending_activity_ignores_undated_mapping() -> None:
    fire = tests.helpers.factories.peri_scribe.presentation.fire_data.pending_activity(
        [(-8, 100)],
        [(-1, 10_000)],
    )
    fire = dataclasses.replace(
        fire,
        perimeters=(dataclasses.replace(fire.perimeters[0], observation_time=None),),
    )
    assert (
        peri_scribe.presentation.fire_data.pending_activity(
            fire,
            tests.helpers.factories.peri_scribe.fires.activity.REFERENCE_TIME,
        )
        is peri_scribe.models.FireStatus.HOLDING
    )


def test_pending_activity_preserves_agency_inactive() -> None:
    fire = tests.helpers.factories.peri_scribe.presentation.fire_data.pending_activity(
        [(-8, 100), (-1, 10_000)],
        [],
    )
    fire = dataclasses.replace(
        fire,
        entry=fire.entry.model_copy(update={"status": "inactive"}),
    )
    assert (
        peri_scribe.presentation.fire_data.pending_activity(
            fire,
            tests.helpers.factories.peri_scribe.fires.activity.REFERENCE_TIME,
        )
        is peri_scribe.models.FireStatus.INACTIVE
    )


def test_prepare_fire_data_reclassifies_without_changing_agency_status() -> None:
    index = tests.helpers.factories.peri_scribe.kml.parsing.fire_index([
        tests.helpers.factories.peri_scribe.kml.parsing.fire_index_entry(
            "Bug",
            "active",
            identifier="id-bug",
        ),
    ])
    points = tests.helpers.factories.peri_scribe.presentation.fire_data.activity_frame()
    empty = points.iloc[:0]
    reference = tests.helpers.factories.peri_scribe.fires.activity.REFERENCE_TIME
    with peri_scribe.execution.sharing():
        (initial,) = peri_scribe.presentation.fire_data.prepare_fire_data(
            index,
            empty,
            points,
            empty,
            reference_time=reference,
        )
        (later,) = peri_scribe.presentation.fire_data.prepare_fire_data(
            index,
            empty,
            points,
            empty,
            reference_time=reference + datetime.timedelta(days=3),
        )
    assert initial.summary.status is peri_scribe.models.FireStatus.ACTIVE
    assert later.summary.status is peri_scribe.models.FireStatus.HOLDING
    assert index.fires[0].status == "active"


def test_presentation_time_explicit_reference_controls_subsequent_views() -> None:
    reference = tests.helpers.factories.peri_scribe.fires.activity.REFERENCE_TIME
    with peri_scribe.execution.sharing():
        peri_scribe.presentation.fire_data.presentation_time(reference)
        assert peri_scribe.presentation.fire_data.presentation_time() == reference


def test_presentation_time_is_shared_only_inside_one_execution() -> None:
    reference = tests.helpers.factories.peri_scribe.fires.activity.REFERENCE_TIME
    with time_machine.travel(reference, tick=False) as clock:
        with peri_scribe.execution.sharing():
            initial = peri_scribe.presentation.fire_data.presentation_time()
            clock.shift(datetime.timedelta(days=4))
            assert peri_scribe.presentation.fire_data.presentation_time() == initial
        assert peri_scribe.presentation.fire_data.presentation_time() == (
            reference + datetime.timedelta(days=4)
        )
