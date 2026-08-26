"""Tests for peri_scribe.kml_tour."""

from __future__ import annotations

import datetime

import pytest
import simplekml

import peri_scribe.kml_tour
import tests.kml_helpers


def test_time_label_returns_none_without_observation_time() -> None:
    assert peri_scribe.kml_tour.time_label(None) is None


def test_time_label_formats_california_time() -> None:
    observation_time = datetime.datetime(2026, 8, 5, 20, 30, tzinfo=datetime.UTC)
    assert peri_scribe.kml_tour.time_label(observation_time) == "08/05 13:30"


def test_interior_placemark_name_without_observation_time() -> None:
    assert peri_scribe.kml_tour.interior_placemark_name(None) == "Interior"


def test_interior_placemark_name_with_observation_time() -> None:
    observation_time = datetime.datetime(2026, 8, 5, 20, 30, tzinfo=datetime.UTC)
    assert peri_scribe.kml_tour.interior_placemark_name(observation_time) == (
        "08/05 13:30 Interior"
    )


def test_mapping_placemark_name_without_observation_time() -> None:
    assert peri_scribe.kml_tour.mapping_placemark_name(None) == "Unknown Mapping"


def test_mapping_placemark_name_with_observation_time() -> None:
    observation_time = datetime.datetime(2026, 8, 5, 20, 30, tzinfo=datetime.UTC)
    assert peri_scribe.kml_tour.mapping_placemark_name(observation_time) == (
        "08/05 13:30 Perimeter"
    )


def test_interior_ring_id_names_folder_and_index() -> None:
    kml = simplekml.Kml()
    folder = kml.document.newfolder(name="Bug")
    assert peri_scribe.kml_tour.interior_ring_id(folder, 3) == (
        f"progression-ring-{folder.id}-3"
    )


def test_tour_wait_in_seconds_scales_days_by_playback_rate() -> None:
    earlier = datetime.datetime(2026, 8, 5, 20, 0, tzinfo=datetime.UTC)
    later = datetime.datetime(2026, 8, 8, 20, 0, tzinfo=datetime.UTC)
    assert peri_scribe.kml_tour.tour_wait_in_seconds(
        earlier,
        later,
        peri_scribe.kml_tour.TOUR_PLAYBACK_SECONDS_PER_DAY,
    ) == pytest.approx(3.0)
    assert peri_scribe.kml_tour.tour_wait_in_seconds(
        earlier,
        later,
        0.5,
    ) == pytest.approx(1.5)


def test_tour_wait_in_seconds_with_missing_observation_time() -> None:
    observation_time = datetime.datetime(2026, 8, 5, 20, 0, tzinfo=datetime.UTC)
    assert peri_scribe.kml_tour.tour_wait_in_seconds(
        None,
        observation_time,
        peri_scribe.kml_tour.TOUR_PLAYBACK_SECONDS_PER_DAY,
    ) == pytest.approx(0.0)
    assert peri_scribe.kml_tour.tour_wait_in_seconds(
        observation_time,
        None,
        peri_scribe.kml_tour.TOUR_PLAYBACK_SECONDS_PER_DAY,
    ) == pytest.approx(0.0)


def test_tour_seconds_per_day_for_short_fire() -> None:
    first = datetime.datetime(2026, 8, 1, 0, 0, tzinfo=datetime.UTC)
    second = datetime.datetime(2026, 8, 6, 0, 0, tzinfo=datetime.UTC)
    assert peri_scribe.kml_tour.tour_seconds_per_day([first, second]) == pytest.approx(
        peri_scribe.kml_tour.TOUR_PLAYBACK_SECONDS_PER_DAY,
    )


def test_tour_seconds_per_day_for_five_day_fire() -> None:
    first = datetime.datetime(2026, 8, 1, 0, 0, tzinfo=datetime.UTC)
    second = datetime.datetime(2026, 8, 6, 0, 0, tzinfo=datetime.UTC)
    assert peri_scribe.kml_tour.tour_seconds_per_day([first, second]) == pytest.approx(
        peri_scribe.kml_tour.TOUR_PLAYBACK_SECONDS_PER_DAY,
    )


def test_tour_seconds_per_day_for_long_fire() -> None:
    first = datetime.datetime(2026, 8, 1, 0, 0, tzinfo=datetime.UTC)
    second = datetime.datetime(2026, 8, 26, 0, 0, tzinfo=datetime.UTC)
    rate = peri_scribe.kml_tour.tour_seconds_per_day([first, second])
    assert rate == pytest.approx(0.2)
    total_in_days = (second - first).total_seconds() / 86_400
    assert total_in_days * rate == pytest.approx(
        peri_scribe.kml_tour.MAX_TOUR_PLAYBACK_IN_SECONDS,
    )


def test_tour_seconds_per_day_without_two_observations() -> None:
    observation_time = datetime.datetime(2026, 8, 5, 20, 0, tzinfo=datetime.UTC)
    assert peri_scribe.kml_tour.tour_seconds_per_day(
        [observation_time],
    ) == pytest.approx(peri_scribe.kml_tour.TOUR_PLAYBACK_SECONDS_PER_DAY)
    assert peri_scribe.kml_tour.tour_seconds_per_day([None]) == pytest.approx(
        peri_scribe.kml_tour.TOUR_PLAYBACK_SECONDS_PER_DAY,
    )
    assert peri_scribe.kml_tour.tour_seconds_per_day([]) == pytest.approx(
        peri_scribe.kml_tour.TOUR_PLAYBACK_SECONDS_PER_DAY,
    )


def test_visibility_change_reveals_rings_through_index() -> None:
    assert peri_scribe.kml_tour.visibility_change(["a", "b", "c"], 1) == (
        '<Placemark targetId="a"><visibility>1</visibility></Placemark>'
        '<Placemark targetId="b"><visibility>1</visibility></Placemark>'
        '<Placemark targetId="c"><visibility>0</visibility></Placemark>'
    )


def test_progression_tour_reveals_rings_and_waits() -> None:
    first = datetime.datetime(2026, 8, 5, 20, 0, tzinfo=datetime.UTC)
    second = datetime.datetime(2026, 8, 8, 20, 0, tzinfo=datetime.UTC)
    third = datetime.datetime(2026, 8, 9, 20, 0, tzinfo=datetime.UTC)
    ring_times = [first, second, third]
    kml = simplekml.Kml()
    folder = kml.document.newfolder(name="Bug")
    peri_scribe.kml_tour.progression_tour(folder, ring_times)
    bug_folder = tests.kml_helpers.folder_named(
        tests.kml_helpers.document_from(kml.kml()),
        "Bug",
    )
    tour = tests.kml_helpers.tour_named(bug_folder, "Progression")
    updates = tests.kml_helpers.tour_primitives(
        tour,
        tests.kml_helpers.gx_tag("AnimatedUpdate"),
    )
    waits = tests.kml_helpers.tour_primitives(tour, tests.kml_helpers.gx_tag("Wait"))
    assert len(updates) == len(ring_times)
    assert len(waits) == len(ring_times)
    ring_ids = [
        peri_scribe.kml_tour.interior_ring_id(folder, index)
        for index in range(len(ring_times))
    ]
    assert [
        tests.kml_helpers.update_visibility_by_target(update) for update in updates
    ] == [
        {ring_ids[0]: 1, ring_ids[1]: 0, ring_ids[2]: 0},
        {ring_ids[0]: 1, ring_ids[1]: 1, ring_ids[2]: 0},
        {ring_ids[0]: 1, ring_ids[1]: 1, ring_ids[2]: 1},
    ]
    assert [tests.kml_helpers.wait_duration(wait) for wait in waits] == [3.0, 1.0, 1.0]


def test_progression_tour_scales_waits_for_long_fire() -> None:
    first = datetime.datetime(2026, 8, 1, 0, 0, tzinfo=datetime.UTC)
    second = datetime.datetime(2026, 8, 6, 0, 0, tzinfo=datetime.UTC)
    third = datetime.datetime(2026, 8, 26, 0, 0, tzinfo=datetime.UTC)
    ring_times = [first, second, third]
    kml = simplekml.Kml()
    folder = kml.document.newfolder(name="Bug")
    peri_scribe.kml_tour.progression_tour(folder, ring_times)
    bug_folder = tests.kml_helpers.folder_named(
        tests.kml_helpers.document_from(kml.kml()),
        "Bug",
    )
    tour = tests.kml_helpers.tour_named(bug_folder, "Progression")
    waits = tests.kml_helpers.tour_primitives(tour, tests.kml_helpers.gx_tag("Wait"))
    assert [tests.kml_helpers.wait_duration(wait) for wait in waits] == pytest.approx([
        1,
        4,
        1,
    ])


def test_assign_placemark_id_sets_placemark_id() -> None:
    kml = simplekml.Kml()
    folder = kml.document.newfolder(name="Bug")
    placemark = folder.newpolygon(
        name="Interior",
        outerboundaryis=[(0, 0), (1, 0), (1, 1), (0, 0)],
    )
    peri_scribe.kml_tour.assign_placemark_id(placemark, "custom-id")
    interior = tests.kml_helpers.placemark_named(
        tests.kml_helpers.folder_named(
            tests.kml_helpers.document_from(kml.kml()),
            "Bug",
        ),
        "Interior",
    )
    assert interior.get("id") == "custom-id"
