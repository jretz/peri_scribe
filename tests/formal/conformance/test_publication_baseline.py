"""Complete publication baseline ownership agrees with the compiled Lean fold."""

import tests.formal.helpers.oracle
import tests.formal.helpers.publication_baseline


def test_published_fires_complete_collection_matches_lean() -> None:
    cases = tests.formal.helpers.publication_baseline.cases()
    expected_count = 4473
    assert len(cases) == expected_count
    expected = tests.formal.helpers.oracle.evaluate(
        [case.command() for case in cases],
        executable="oraclePublicationBaseline",
    )
    for case, result in zip(cases, expected, strict=True):
        tests.formal.helpers.publication_baseline.check(case, result)
