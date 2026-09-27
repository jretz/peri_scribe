"""Qualified output facts preserve the checked publication baseline."""

import pathlib

import tests.formal.helpers.oracle
import tests.formal.helpers.publication_baseline_output


def test_published_fires_matches_qualified_output_and_persisted_baseline(
    tmp_path: pathlib.Path,
) -> None:
    cases = tests.formal.helpers.publication_baseline_output.cases()
    expected_count = 17
    assert len(cases) == expected_count
    expected = tests.formal.helpers.oracle.evaluate(
        [case.case.command() for case in cases],
        executable="oraclePublicationBaseline",
    )
    for index, (case, result) in enumerate(zip(cases, expected, strict=True)):
        tests.formal.helpers.publication_baseline_output.check(
            case,
            result,
            tmp_path / str(index),
        )
