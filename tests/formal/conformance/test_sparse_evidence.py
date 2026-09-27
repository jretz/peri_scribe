import tests.formal.helpers.oracle
import tests.formal.helpers.sparse_evidence


def test_prepare_history_matches_sparse_evidence_and_dated_visibility_proofs() -> None:
    cases = tests.formal.helpers.sparse_evidence.cases()
    expected = tests.formal.helpers.oracle.evaluate(
        [case.command() for case in cases],
        executable="oraclePresentation",
    )
    for case, outcome in zip(cases, expected, strict=True):
        tests.formal.helpers.sparse_evidence.check(case, outcome)
