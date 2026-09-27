"""Publication evidence agrees with checked capture, ownership, and comparison folds."""

import itertools

import pytest

import peri_scribe.publication
import tests.formal.helpers.oracle
import tests.formal.helpers.publication_evidence


EXCLUDED_BASELINE = -2


def test_first_captures_uses_earliest_evidence_and_is_idempotent() -> None:
    cases = tests.formal.helpers.publication_evidence.histories()
    expected = tests.formal.helpers.oracle.evaluate(
        [" ".join(["first", *(value.command() for value in case)]) for case in cases],
        executable="oracleEvidence",
    )
    for case, result in zip(cases, expected, strict=True):
        snapshots: dict[str, tuple[peri_scribe.publication.Mapping, ...]] = {
            f"{value.identity}.gpkg": (value.production(),) for value in case
        }
        updated = peri_scribe.publication.first_captures(snapshots)
        assert (
            tuple(
                int(
                    (
                        mapping.captured_at
                        - tests.formal.helpers.publication_evidence.BASE
                    ).total_seconds(),
                )
                for mappings in updated.values()
                for mapping in mappings
            )
            == result
        )
        assert peri_scribe.publication.first_captures(updated) == updated


def test_candidate_fires_handles_collapsed_aliases_ambiguity_and_order() -> None:
    cases = [
        (history, owners)
        for history in tests.formal.helpers.publication_evidence.histories()
        for owners in ((), ((0, 10),), ((0, 10), (1, 11)), ((0, 10), (1, 10)))
    ]
    expected = tests.formal.helpers.oracle.evaluate(
        [
            " ".join([
                "candidates",
                ";".join(f"{identifier},{owner}" for identifier, owner in owners)
                or "none",
                *(value.command() for value in history),
            ])
            for history, owners in cases
        ],
        executable="oracleEvidence",
    )
    for (history, owners), result in zip(cases, expected, strict=True):
        assert (
            tests.formal.helpers.publication_evidence.candidate_result(history, owners)
            == result
        )


def test_mapping_decision_selects_largest_eligible_change_including_shrinkage() -> None:
    cases = [
        (history, threshold)
        for history in tests.formal.helpers.publication_evidence.comparisons()
        for threshold in (0, 1, 25, 100)
    ]
    expected = tests.formal.helpers.oracle.evaluate(
        [
            " ".join([
                "compare",
                str(threshold),
                *(value.command() for value in history),
            ])
            for history, threshold in cases
        ],
        executable="oracleEvidence",
    )
    for (history, threshold), result in zip(cases, expected, strict=True):
        assert (
            tests.formal.helpers.publication_evidence.comparison_result(
                history,
                threshold,
            )
            == result
        )


def test_published_fires_requires_unique_raw_source_for_displayed_baseline() -> None:
    cases = [
        (rows, file, object_id, included)
        for rows in tests.formal.helpers.publication_evidence.raw_sources()
        for file, object_id, included in itertools.product(
            range(2),
            range(2),
            (False, True),
        )
    ]
    expected = tests.formal.helpers.oracle.evaluate(
        [
            " ".join([
                "raw",
                str(file),
                str(object_id),
                str(int(included)),
                *(row.command() for row in rows),
            ])
            for rows, file, object_id, included in cases
        ],
        executable="oracleEvidence",
    )
    for (rows, file, object_id, included), (result,) in zip(
        cases,
        expected,
        strict=True,
    ):
        if result == -1:
            with pytest.raises(
                ValueError,
                match="Cannot identify published mapping source",
            ):
                tests.formal.helpers.publication_evidence.published_baseline(
                    rows,
                    file,
                    object_id,
                    included=included,
                )
        else:
            fire = tests.formal.helpers.publication_evidence.published_baseline(
                rows,
                file,
                object_id,
                included=included,
            )
            if result == EXCLUDED_BASELINE:
                assert fire.mapping is None
            else:
                assert fire.mapping is not None
                assert int(fire.mapping.name) == result
                assert fire.mapping.area_square_meters == rows[result].mapping.area
                assert set(fire.identifiers) == {"i0", "i1", "i2"}
