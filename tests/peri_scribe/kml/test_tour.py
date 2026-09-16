"""Tests for peri_scribe.kml.tour."""

from __future__ import annotations

import datetime

import hypothesis
import pytest

import peri_scribe.kml.geometry
import peri_scribe.kml.tour
import tests.peri_scribe.kml.kml_helpers
import tests.peri_scribe.kml.tour_helpers


@hypothesis.given(times=tests.peri_scribe.kml.tour_helpers.ring_times())
def test_progression_tour_preserves_elapsed_time_within_playback_budget(
    times: list[datetime.datetime | None],
) -> None:
    tour = tests.peri_scribe.kml.tour_helpers.rendered_tour(times)
    waits = tests.peri_scribe.kml.kml_helpers.tour_primitives(
        tour,
        tests.peri_scribe.kml.kml_helpers.gx_tag("Wait"),
    )
    durations = [
        tests.peri_scribe.kml.kml_helpers.wait_duration(wait) for wait in waits
    ]
    assert len(durations) == len(times)
    assert all(duration >= 0 for duration in durations)
    if not times:
        return
    assert durations[-1] == peri_scribe.kml.tour.FINAL_TOUR_WAIT.m_as("seconds")
    observed = [time for time in times if time is not None]
    days = (observed[-1] - observed[0]) / datetime.timedelta(days=1) if observed else 0
    expected = min(
        days * peri_scribe.kml.tour.TOUR_PLAYBACK_RATE,
        peri_scribe.kml.tour.MAXIMUM_TOUR_PLAYBACK.m_as("seconds"),
    )
    assert sum(durations[:-1]) == pytest.approx(expected, rel=1e-12, abs=1e-12)


@hypothesis.given(times=tests.peri_scribe.kml.tour_helpers.ring_times())
def test_progression_tour_reveals_exactly_one_more_ring_per_step(
    times: list[datetime.datetime | None],
) -> None:
    tour = tests.peri_scribe.kml.tour_helpers.rendered_tour(times)
    updates = tests.peri_scribe.kml.kml_helpers.tour_primitives(
        tour,
        tests.peri_scribe.kml.kml_helpers.gx_tag("AnimatedUpdate"),
    )
    states = [
        tests.peri_scribe.kml.kml_helpers.update_visibility_by_target(update)
        for update in updates
    ]
    assert len(states) == len(times)
    targets = list(states[0]) if states else []
    assert len(targets) == len(times)
    for revealed, state in enumerate(states, start=1):
        assert set(state) == set(targets)
        assert set(state.values()) <= {0, 1}
        assert {target for target, visible in state.items() if visible} == set(
            targets[:revealed],
        )


def test_time_label_returns_none_without_observation_time() -> None:
    assert peri_scribe.kml.tour.time_label(None) is None


def test_time_label_formats_california_time() -> None:
    observation_time = datetime.datetime(2026, 8, 5, 20, 30, tzinfo=datetime.UTC)
    assert peri_scribe.kml.tour.time_label(observation_time) == "08/05 13:30"


def test_interior_placemark_name_without_observation_time() -> None:
    assert peri_scribe.kml.tour.interior_placemark_name(None) == "Interior"


def test_interior_placemark_name_with_observation_time() -> None:
    observation_time = datetime.datetime(2026, 8, 5, 20, 30, tzinfo=datetime.UTC)
    assert peri_scribe.kml.tour.interior_placemark_name(observation_time) == (
        "08/05 13:30 Interior"
    )


def test_mapping_placemark_name_without_observation_time() -> None:
    assert peri_scribe.kml.tour.mapping_placemark_name(None) == "Unknown Mapping"


def test_mapping_placemark_name_with_observation_time() -> None:
    observation_time = datetime.datetime(2026, 8, 5, 20, 30, tzinfo=datetime.UTC)
    assert peri_scribe.kml.tour.mapping_placemark_name(observation_time) == (
        "08/05 13:30 Perimeter"
    )


def test_interior_ring_id_names_folder_and_index() -> None:
    assert peri_scribe.kml.tour.interior_ring_id("folder-7", 3) == (
        "progression-ring-folder-7-3"
    )


def test_tour_wait_scales_days_by_playback_rate() -> None:
    earlier = datetime.datetime(2026, 8, 5, 20, 0, tzinfo=datetime.UTC)
    later = datetime.datetime(2026, 8, 8, 20, 0, tzinfo=datetime.UTC)
    assert peri_scribe.kml.tour.tour_wait(
        earlier,
        later,
        peri_scribe.kml.tour.TOUR_PLAYBACK_RATE,
    ).m_as("seconds") == pytest.approx(3.0)
    assert peri_scribe.kml.tour.tour_wait(earlier, later, 0.5).m_as(
        "seconds",
    ) == pytest.approx(1.5)


def test_tour_wait_with_missing_observation_time() -> None:
    observation_time = datetime.datetime(2026, 8, 5, 20, 0, tzinfo=datetime.UTC)
    assert peri_scribe.kml.tour.tour_wait(
        None,
        observation_time,
        peri_scribe.kml.tour.TOUR_PLAYBACK_RATE,
    ).m_as("seconds") == pytest.approx(0.0)
    assert peri_scribe.kml.tour.tour_wait(
        observation_time,
        None,
        peri_scribe.kml.tour.TOUR_PLAYBACK_RATE,
    ).m_as("seconds") == pytest.approx(0.0)


def test_tour_playback_rate_for_short_fire() -> None:
    first = datetime.datetime(2026, 8, 1, 0, 0, tzinfo=datetime.UTC)
    second = datetime.datetime(2026, 8, 6, 0, 0, tzinfo=datetime.UTC)
    assert peri_scribe.kml.tour.tour_playback_rate([first, second]) == pytest.approx(
        peri_scribe.kml.tour.TOUR_PLAYBACK_RATE,
    )


def test_tour_playback_rate_for_five_day_fire() -> None:
    first = datetime.datetime(2026, 8, 1, 0, 0, tzinfo=datetime.UTC)
    second = datetime.datetime(2026, 8, 6, 0, 0, tzinfo=datetime.UTC)
    assert peri_scribe.kml.tour.tour_playback_rate([first, second]) == pytest.approx(
        peri_scribe.kml.tour.TOUR_PLAYBACK_RATE,
    )


def test_tour_playback_rate_for_long_fire() -> None:
    first = datetime.datetime(2026, 8, 1, 0, 0, tzinfo=datetime.UTC)
    second = datetime.datetime(2026, 8, 26, 0, 0, tzinfo=datetime.UTC)
    rate = peri_scribe.kml.tour.tour_playback_rate([first, second])
    assert rate == pytest.approx(0.2)
    total_in_days = (second - first).total_seconds() / 86_400
    assert total_in_days * rate == pytest.approx(
        peri_scribe.kml.tour.MAXIMUM_TOUR_PLAYBACK.m_as("seconds"),
    )


def test_tour_playback_rate_without_two_observations() -> None:
    observation_time = datetime.datetime(2026, 8, 5, 20, 0, tzinfo=datetime.UTC)
    assert peri_scribe.kml.tour.tour_playback_rate([observation_time]) == pytest.approx(
        peri_scribe.kml.tour.TOUR_PLAYBACK_RATE,
    )
    assert peri_scribe.kml.tour.tour_playback_rate([None]) == pytest.approx(
        peri_scribe.kml.tour.TOUR_PLAYBACK_RATE,
    )
    assert peri_scribe.kml.tour.tour_playback_rate([]) == pytest.approx(
        peri_scribe.kml.tour.TOUR_PLAYBACK_RATE,
    )


def test_visibility_change_reveals_rings_through_index() -> None:
    assert peri_scribe.kml.tour.visibility_change(["a", "b", "c"], 1) == (
        '<Placemark targetId="a"><visibility>1</visibility></Placemark>'
        '<Placemark targetId="b"><visibility>1</visibility></Placemark>'
        '<Placemark targetId="c"><visibility>0</visibility></Placemark>'
    )


def test_progression_tour_reveals_rings_and_waits() -> None:
    first = datetime.datetime(2026, 8, 5, 20, 0, tzinfo=datetime.UTC)
    second = datetime.datetime(2026, 8, 8, 20, 0, tzinfo=datetime.UTC)
    third = datetime.datetime(2026, 8, 9, 20, 0, tzinfo=datetime.UTC)
    ring_times = [first, second, third]
    writer = peri_scribe.kml.geometry.KmlWriter()
    with writer.folder("Bug") as folder_id:
        peri_scribe.kml.tour.progression_tour(writer, folder_id, ring_times)
    bug_folder = tests.peri_scribe.kml.kml_helpers.folder_named(
        tests.peri_scribe.kml.kml_helpers.document_from_writer(writer),
        "Bug",
    )
    tour = tests.peri_scribe.kml.kml_helpers.tour_named(bug_folder, "Progression")
    updates = tests.peri_scribe.kml.kml_helpers.tour_primitives(
        tour,
        tests.peri_scribe.kml.kml_helpers.gx_tag("AnimatedUpdate"),
    )
    waits = tests.peri_scribe.kml.kml_helpers.tour_primitives(
        tour,
        tests.peri_scribe.kml.kml_helpers.gx_tag("Wait"),
    )
    assert len(updates) == len(ring_times)
    assert len(waits) == len(ring_times)
    ring_ids = [
        peri_scribe.kml.tour.interior_ring_id(folder_id, index)
        for index in range(len(ring_times))
    ]
    assert [
        tests.peri_scribe.kml.kml_helpers.update_visibility_by_target(update)
        for update in updates
    ] == [
        {ring_ids[0]: 1, ring_ids[1]: 0, ring_ids[2]: 0},
        {ring_ids[0]: 1, ring_ids[1]: 1, ring_ids[2]: 0},
        {ring_ids[0]: 1, ring_ids[1]: 1, ring_ids[2]: 1},
    ]
    assert [
        tests.peri_scribe.kml.kml_helpers.wait_duration(wait) for wait in waits
    ] == [3.0, 1.0, 1.0]


def test_progression_tour_scales_waits_for_long_fire() -> None:
    first = datetime.datetime(2026, 8, 1, 0, 0, tzinfo=datetime.UTC)
    second = datetime.datetime(2026, 8, 6, 0, 0, tzinfo=datetime.UTC)
    third = datetime.datetime(2026, 8, 26, 0, 0, tzinfo=datetime.UTC)
    ring_times = [first, second, third]
    writer = peri_scribe.kml.geometry.KmlWriter()
    with writer.folder("Bug") as folder_id:
        peri_scribe.kml.tour.progression_tour(writer, folder_id, ring_times)
    bug_folder = tests.peri_scribe.kml.kml_helpers.folder_named(
        tests.peri_scribe.kml.kml_helpers.document_from_writer(writer),
        "Bug",
    )
    tour = tests.peri_scribe.kml.kml_helpers.tour_named(bug_folder, "Progression")
    waits = tests.peri_scribe.kml.kml_helpers.tour_primitives(
        tour,
        tests.peri_scribe.kml.kml_helpers.gx_tag("Wait"),
    )
    assert [
        tests.peri_scribe.kml.kml_helpers.wait_duration(wait) for wait in waits
    ] == pytest.approx([1, 4, 1])


def test_progression_tour_assigns_targeted_placemark_ids() -> None:
    observation_time = datetime.datetime(2026, 8, 5, 20, 0, tzinfo=datetime.UTC)
    writer = peri_scribe.kml.geometry.KmlWriter()
    with writer.folder("Bug") as folder_id:
        peri_scribe.kml.tour.progression_tour(writer, folder_id, [observation_time])
    bug_folder = tests.peri_scribe.kml.kml_helpers.folder_named(
        tests.peri_scribe.kml.kml_helpers.document_from_writer(writer),
        "Bug",
    )
    tour = tests.peri_scribe.kml.kml_helpers.tour_named(bug_folder, "Progression")
    update = tests.peri_scribe.kml.kml_helpers.tour_primitives(
        tour,
        tests.peri_scribe.kml.kml_helpers.gx_tag("AnimatedUpdate"),
    )[0]
    assert tests.peri_scribe.kml.kml_helpers.update_visibility_by_target(update) == {
        peri_scribe.kml.tour.interior_ring_id(folder_id, 0): 1,
    }
