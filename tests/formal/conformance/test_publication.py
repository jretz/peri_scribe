import itertools

import tests.formal.helpers.oracle
import tests.formal.helpers.publication


def test_decide_matches_lean_gate_precedence_and_timer_boundary() -> None:
    cases = [
        tests.formal.helpers.publication.Gate(
            valid=valid,
            evacuations=evacuations,
            cities=cities,
            history=history,
            pending=pending,
            mapping=mapping,
            elapsed=elapsed,
        )
        for valid, evacuations, cities, history, pending, mapping in itertools.product(
            (False, True),
            repeat=6,
        )
        for elapsed in (-1, 0, 299, 300, 301)
    ]
    expected = tests.formal.helpers.oracle.evaluate([case.command() for case in cases])
    for case, result in zip(cases, expected, strict=True):
        decision = tests.formal.helpers.publication.implementation_decision(case)
        assert (decision.proceed, decision.reason) == (
            bool(result[0]),
            tests.formal.helpers.publication.REASONS[result[1]],
        ), case
