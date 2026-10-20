"""Check the ordered matching boundary for perimeter publications."""

from __future__ import annotations

import dataclasses
import datetime

import pytest
import shapely

import peri_scribe.perimeters.versions
import tests.helpers.factories.peri_scribe.perimeters.versions
import tests.helpers.factories.time


def test_identical_observation_index_returns_none_for_empty_history() -> None:
    observation = tests.helpers.factories.peri_scribe.perimeters.versions.observation()
    assert (
        peri_scribe.perimeters.versions.identical_observation_index([], observation)
        is None
    )


def test_identical_observation_index_retains_first_match_in_input_order() -> None:
    time = tests.helpers.factories.time.utc(2026, 8, 16, 12)
    observation = tests.helpers.factories.peri_scribe.perimeters.versions.observation(
        geometry=shapely.box(0, 0, 1, 1),
        observation_time=time,
    )
    versions = [
        dataclasses.replace(
            observation,
            observation_time=time - datetime.timedelta(days=1),
        ),
        dataclasses.replace(
            observation,
            geometry=shapely.MultiPolygon([shapely.reverse(shapely.box(0, 0, 1, 1))]),
            observation_time=time + datetime.timedelta(hours=4),
        ),
        dataclasses.replace(
            observation,
            observation_time=time - datetime.timedelta(hours=4),
        ),
    ]
    assert (
        peri_scribe.perimeters.versions.identical_observation_index(
            versions,
            observation,
        )
        == 1
    )


def test_identical_observation_index_skips_distant_geometry_comparisons(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    time = tests.helpers.factories.time.utc(2026, 8, 16, 12)
    observation = tests.helpers.factories.peri_scribe.perimeters.versions.observation(
        geometry=shapely.box(0, 0, 1, 1),
        observation_time=time,
    )
    existing = dataclasses.replace(
        observation,
        observation_time=time + datetime.timedelta(hours=4, microseconds=1),
    )
    monkeypatch.setattr(
        peri_scribe.perimeters.versions,
        "geometries_are_equal",
        lambda *_arguments: pytest.fail("Distant publications need no geometry work"),
    )
    assert (
        peri_scribe.perimeters.versions.identical_observation_index(
            [existing],
            observation,
        )
        is None
    )


@pytest.mark.parametrize(
    ("left_clock", "right_clock", "expected"),
    [
        (None, None, 0),
        (None, "observed", None),
        ("observed", None, None),
        ("modified", "observed", 0),
        ("snapshot", "observed", 0),
    ],
)
def test_identical_observation_index_uses_effective_and_missing_clocks(
    left_clock: str | None,
    right_clock: str | None,
    expected: int | None,
) -> None:
    time = tests.helpers.factories.time.utc(2026, 8, 16, 12)
    observations = [
        tests.helpers.factories.peri_scribe.perimeters.versions.observation(
            geometry=None,
            observation_time=time if clock == "observed" else None,
            snapshot_time=time if clock == "snapshot" else None,
            attributes={"EditDate": time} if clock == "modified" else {},
        )
        for clock in (left_clock, right_clock)
    ]
    assert (
        peri_scribe.perimeters.versions.identical_observation_index(
            observations[:1],
            observations[1],
        )
        == expected
    )


@pytest.mark.parametrize("reverse", [False, True])
def test_identical_observation_index_skips_distinct_shapes_with_incompatible_clocks(
    *,
    reverse: bool,
) -> None:
    time = tests.helpers.factories.time.utc(2026, 8, 16, 12)
    observations = [
        tests.helpers.factories.peri_scribe.perimeters.versions.observation(
            geometry=shapely.box(0, 0, 1, 1),
            observation_time=time,
        ),
        tests.helpers.factories.peri_scribe.perimeters.versions.observation(
            geometry=shapely.box(0, 0, 2, 2),
            observation_time=time.replace(tzinfo=None),
        ),
    ]
    if reverse:
        observations.reverse()
    assert (
        peri_scribe.perimeters.versions.identical_observation_index(
            observations[:1],
            observations[1],
        )
        is None
    )


@pytest.mark.parametrize("reverse", [False, True])
def test_identical_observation_index_rejects_equal_shapes_with_incompatible_clocks(
    *,
    reverse: bool,
) -> None:
    time = tests.helpers.factories.time.utc(2026, 8, 16, 12)
    first = tests.helpers.factories.peri_scribe.perimeters.versions.observation(
        geometry=shapely.box(0, 0, 1, 1),
        observation_time=time,
    )
    observations = [
        first,
        dataclasses.replace(
            first,
            observation_time=time.replace(
                tzinfo=None,
            ),
        ),
    ]
    if reverse:
        observations.reverse()
    with pytest.raises(TypeError, match=r"naive.*aware|aware.*naive"):
        peri_scribe.perimeters.versions.identical_observation_index(
            observations[:1],
            observations[1],
        )
