import itertools

import peri_scribe.incidents
import tests.formal.helpers.incidents
import tests.formal.helpers.oracle


def test_simultaneous_updates_matches_lean_measurement_and_provenance_winner() -> None:
    cases = list(itertools.product((0, 1, 100), (0, 1, 100), (-1, 0, 1), (-1, 0, 1)))
    expected = tests.formal.helpers.oracle.evaluate([
        f"winner {previous} 1 {previous_time} {current} 2 {current_time}"
        for previous, current, previous_time, current_time in cases
    ])
    for case, result in zip(cases, expected, strict=True):
        previous, current, previous_time, current_time = case
        updates = peri_scribe.incidents.simultaneous_updates((
            tests.formal.helpers.incidents.measurement(previous, 1, previous_time),
            tests.formal.helpers.incidents.measurement(current, 2, current_time),
        ))
        assert len(updates) == 1
        assert tests.formal.helpers.incidents.evidence(updates[0]) == result, case


def test_reconcile_updates_matches_lean_confirmed_value_preservation() -> None:
    cases = list(
        itertools.product(
            (0, 10, 100),
            (0, 9, 10, 11, 100),
            (False, True),
            (False, True),
            (False, True),
        ),
    )
    expected = tests.formal.helpers.oracle.evaluate([
        f"preserve {previous} {current} {int(confirmed)} {int(stale)} {int(area)}"
        for previous, current, confirmed, stale, area in cases
    ])
    for case, result in zip(cases, expected, strict=True):
        previous, current, confirmed, stale, area = case
        column = "incident_size" if area else "personnel"
        updates = peri_scribe.incidents.reconcile_updates((
            tests.formal.helpers.incidents.measurement(
                current,
                2,
                0 if stale else 1,
                observed=11,
                column=column,
                confirmed=confirmed,
            ),
            tests.formal.helpers.incidents.measurement(previous, 1, 0, column=column),
        ))
        assert updates[-1].measurements[column] == result[0], case
