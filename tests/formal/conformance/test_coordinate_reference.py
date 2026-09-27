import itertools

import pytest

import arcgis_access.spatial_reference
import tests.formal.helpers.coordinate_reference
import tests.formal.helpers.oracle


def test_axis_fits_matches_proved_interval_containment() -> None:
    cases = tests.formal.helpers.coordinate_reference.axis_cases()
    expected = tests.formal.helpers.oracle.evaluate(
        [
            "axis|" + tests.formal.helpers.coordinate_reference.integers(case)
            for case in cases
        ],
        executable="oracleCoordinateReference",
    )
    for case, (fits,) in zip(cases, expected, strict=True):
        assert arcgis_access.spatial_reference.axis_fits(*case) == bool(fits)


def test_longitudes_in_area_matches_proved_extent_policy() -> None:
    points = (-180.0, -179.0, -170.0, -10.0, 0.0, 10.0, 170.0, 179.0, 180.0)
    cases = [
        (west, east, low, high)
        for west, east, low, high in itertools.product(points, repeat=4)
        if low <= high
    ]
    expected = tests.formal.helpers.oracle.evaluate(
        [
            "longitude|" + tests.formal.helpers.coordinate_reference.integers(case)
            for case in cases
        ],
        executable="oracleCoordinateReference",
    )
    for case, (fits,) in zip(cases, expected, strict=True):
        assert arcgis_access.spatial_reference.longitudes_in_area(*case) == bool(fits)


@pytest.mark.parametrize(
    "extent",
    tests.formal.helpers.coordinate_reference.EXTENTS.values(),
    ids=tests.formal.helpers.coordinate_reference.EXTENTS,
)
def test_select_spatial_reference_wkid_matches_complete_candidate_policy(
    extent: tests.formal.helpers.coordinate_reference.Bounds | None,
) -> None:
    cases = tests.formal.helpers.coordinate_reference.selection_cases(extent)
    commands = list(
        itertools.starmap(tests.formal.helpers.coordinate_reference.command, cases),
    )
    expected = tests.formal.helpers.oracle.evaluate(
        commands,
        executable="oracleCoordinateReference",
    )
    reversed_expected = tests.formal.helpers.oracle.evaluate(
        [
            tests.formal.helpers.coordinate_reference.command(
                tuple(reversed(keys)),
                bounds,
            )
            for keys, bounds in cases
        ],
        executable="oracleCoordinateReference",
    )
    for (identifiers, bounds), result, reversed_result in zip(
        cases,
        expected,
        reversed_expected,
        strict=True,
    ):
        chosen, *kinds = result
        assert chosen == reversed_result[0]
        actual = arcgis_access.spatial_reference.select_spatial_reference_wkid(
            set(identifiers),
            bounds,
        )
        assert actual.wkid == (None if chosen < 0 else chosen)
        assert bool(actual.failure_message) == (chosen < 0)
        if bounds is not None:
            matching, outside, excluded = (
                arcgis_access.spatial_reference.classify_candidates_for_bounds(
                    set(identifiers),
                    bounds,
                )
            )
            assert matching == sorted(
                key
                for key, kind in zip(identifiers, kinds, strict=True)
                if kind == tests.formal.helpers.coordinate_reference.MATCHING
            )
            assert set(outside) == {
                key for key, kind in zip(identifiers, kinds, strict=True) if kind == 1
            }
            assert len(excluded) == kinds.count(0)
            assert (actual.warning is not None) == (
                chosen >= 0 and (kinds.count(1) > 0 or kinds.count(0) > 0)
            )
