import tests.formal.helpers.oracle
import tests.formal.helpers.scoring


def test_fire_score_for_matches_lean_at_every_score_tier() -> None:
    cases = tests.formal.helpers.scoring.score_cases()
    expected = tests.formal.helpers.oracle.evaluate([
        "score " + " ".join(map(str, case)) for case in cases
    ])
    for case, result in zip(cases, expected, strict=True):
        assert tests.formal.helpers.scoring.implementation_score(case) == result[0], (
            case
        )
