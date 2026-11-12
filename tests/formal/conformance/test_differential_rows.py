"""Complete differential rows preserve source evidence through visibility selection."""

import tests.formal.helpers.differential_rows
import tests.formal.helpers.oracle


def test_differential_rows_for_fire_matches_proved_attribution_and_sparse_deltas() -> (
    None
):
    cases = tests.formal.helpers.differential_rows.histories()
    footprints = {
        small: tests.formal.helpers.differential_rows.measured_footprints(small=small)
        for small in (False, True)
    }
    area_tables = {
        small: tests.formal.helpers.differential_rows.area_table(measured)
        for small, measured in footprints.items()
    }
    visible_areas: dict[bytes, float] = {}
    commands = [
        tests.formal.helpers.differential_rows.command(case, areas=area_tables[small])
        for case in cases
        for small in (False, True)
    ]
    responses = iter(
        tests.formal.helpers.oracle.evaluate(
            commands,
            executable="oracleSpatial",
        ),
    )
    for case in cases:
        for small in (False, True):
            expected = tests.formal.helpers.differential_rows.records(next(responses))
            actual = tests.formal.helpers.differential_rows.production(
                case,
                small=small,
                candidates=expected,
            )
            tests.formal.helpers.differential_rows.assert_rows(
                case,
                expected,
                actual,
                footprints=footprints[small],
                visible_areas=visible_areas,
            )


def test_differential_rows_for_fire_keeps_omitted_candidate_source_measurements() -> (
    None
):
    source_type = tests.formal.helpers.differential_rows.Source
    case = [
        source_type(identity=0, shape=1, time=0, values=(10, 0, None, 10)),
        source_type(identity=1, shape=3, time=1, values=(20, None, 5, 20)),
        source_type(identity=2, shape=3, time=2, values=(30, 5, 10, None)),
        source_type(identity=3, shape=7, time=None, values=(None, 10, None, 40)),
        source_type(identity=4, shape=15, time=4, values=(60, 20, 0, 50)),
    ]
    omissions = [(0,), (1,), (3,), (0, 1), (1, 3)]
    footprints = tests.formal.helpers.differential_rows.measured_footprints(small=False)
    areas = tests.formal.helpers.differential_rows.area_table(footprints)
    visible_areas: dict[bytes, float] = {}
    expected = tests.formal.helpers.oracle.evaluate(
        [
            tests.formal.helpers.differential_rows.command(
                case,
                areas=areas,
                omitted=omitted,
            )
            for omitted in omissions
        ],
        executable="oracleSpatial",
    )
    for omitted, response in zip(omissions, expected, strict=True):
        records = tests.formal.helpers.differential_rows.records(response)
        actual = tests.formal.helpers.differential_rows.production(
            case,
            small=False,
            candidates=records,
            omitted=omitted,
        )
        tests.formal.helpers.differential_rows.assert_rows(
            case,
            records,
            actual,
            footprints=footprints,
            visible_areas=visible_areas,
        )
