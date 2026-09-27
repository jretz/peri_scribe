"""Competing current aliases obey checked reversible history ownership."""

import pathlib

import tests.formal.helpers.identity_transfer


def test_resolved_ownership_matches_latest_alias_claims_and_retained_buckets() -> None:
    expected = 291
    assert tests.formal.helpers.identity_transfer.check_batches() == expected


def test_publications_preserve_evidence_and_reversibly_project_immutable_logs(
    tmp_path: pathlib.Path,
) -> None:
    expected = 26
    assert (
        tests.formal.helpers.identity_transfer.check_publications(tmp_path) == expected
    )


def test_real_source_grouping_collapses_overlapping_aliases_before_publication(
    tmp_path: pathlib.Path,
) -> None:
    tests.formal.helpers.identity_transfer.check_grouped_publication(tmp_path)
