"""Version reconciliation and survey freshness agree with the proved Lean folds."""

import itertools

import peri_scribe.perimeters.versions
import tests.formal.helpers.oracle
import tests.formal.helpers.perimeter_evidence


def test_collapse_mapping_revisions_preserves_winners_times_and_lineage() -> None:
    histories = tests.formal.helpers.perimeter_evidence.histories()
    commands = [
        " ".join([operation, *(value.command() for value in history)])
        for history in histories
        for operation in ("collapse", "revisions")
    ]
    expected = iter(
        tests.formal.helpers.oracle.evaluate(
            commands,
            executable="oracleEvidence",
        ),
    )
    for history in histories:
        actual = [value.production() for value in history]
        collapsed = (
            peri_scribe.perimeters.versions.collapse_identical_consecutive_perimeters(
                list(reversed(actual)),
            )
        )
        revised = peri_scribe.perimeters.versions.collapse_mapping_revisions(actual)
        assert tests.formal.helpers.perimeter_evidence.retained(collapsed) == next(
            expected,
        ), history
        assert tests.formal.helpers.perimeter_evidence.retained(revised) == next(
            expected,
        ), history


def test_new_capture_requires_fresh_metadata() -> None:
    pairs = [
        (previous, current)
        for history in tests.formal.helpers.perimeter_evidence.histories()
        for previous, current in itertools.pairwise(history)
    ]
    expected = tests.formal.helpers.oracle.evaluate(
        [
            f"capture {previous.command()} {current.command()}"
            for previous, current in pairs
        ],
        executable="oracleEvidence",
    )
    for (previous, current), result in zip(pairs, expected, strict=True):
        assert (
            int(
                peri_scribe.perimeters.versions.new_capture(
                    previous.production(),
                    current.production(),
                ),
            ),
        ) == result, (previous, current)


def test_drop_losing_source_versions_retains_preferred_source_and_lineage() -> None:
    cases = tests.formal.helpers.perimeter_evidence.supersession_cases()
    expected = tests.formal.helpers.oracle.evaluate(
        [
            " ".join([
                "absorb",
                current.command(),
                *(item.command() for item in preferred),
            ])
            for current, preferred in cases
        ],
        executable="oracleEvidence",
    )
    for (current, preferred), result in zip(cases, expected, strict=True):
        actual = peri_scribe.perimeters.versions.drop_losing_source_versions(
            [current.production(), *(item.production() for item in preferred)],
            peri_scribe.perimeters.versions.FIRIS_PERIMETER,
        )
        if result == (-1,):
            assert len(actual) == len(preferred) + 1
            assert current.identity in [
                int(item.source_file.split(".")[0]) for item in actual
            ]
        else:
            descending = sorted(
                actual,
                key=peri_scribe.perimeters.versions.perimeter_sort_key,
                reverse=True,
            )
            assert (
                tests.formal.helpers.perimeter_evidence.retained(descending) == result
            )


def test_mapping_history_retains_last_actual_survey_across_republications() -> None:
    cases = tests.formal.helpers.perimeter_evidence.survey_histories()
    geometries = tests.formal.helpers.perimeter_evidence.survey_geometries()
    differences = tests.formal.helpers.perimeter_evidence.survey_matrix(geometries)
    expected = tests.formal.helpers.oracle.evaluate(
        [
            " ".join(["survey", differences, *(value.command() for value in case)])
            for case in cases
        ],
        executable="oracleEvidence",
    )
    for case, result in zip(cases, expected, strict=True):
        assert (
            tests.formal.helpers.perimeter_evidence.survey_result(case, geometries)
            == result
        ), case
