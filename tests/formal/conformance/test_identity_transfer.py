"""Competing current aliases obey checked reversible history ownership."""

import pathlib

import pytest

import tests.formal.helpers.identity_transfer
import tests.formal.helpers.oracle


@pytest.mark.parametrize(
    ("queries", "lineage", "claimants"),
    [
        ("", "", ("1,n,3,n",)),
        ("4 7 2", "n", ()),
        ("7 7 2 9", "3,7:7 3,2 5,7:9", ("1,n,3,n", "2,1,5,2", "3,1,5,2")),
    ],
    ids=["no-histories", "no-claimants", "ordered-duplicates"],
)
def test_claim_inventory_preserves_whole_and_singleton_queries(
    queries: str,
    lineage: str,
    claimants: tuple[str, ...],
) -> None:
    inventory = " ".join(claimants)
    original = tests.formal.helpers.oracle.evaluate(
        [f"claim|{queries}|{lineage}|{scope}" for scope in (inventory, *claimants)],
        executable="oracleIdentityTransfer",
    )
    packed = tests.formal.helpers.oracle.evaluate(
        [f"claim-inventory|{queries}|{lineage}|{inventory}"],
        executable="oracleIdentityTransfer",
    )
    assert packed == [tuple(claimant for row in original for claimant in row)]


def test_resolved_ownership_matches_latest_alias_claims_and_retained_buckets() -> None:
    expected = 259
    assert tests.formal.helpers.identity_transfer.check_batches() == expected


@pytest.mark.usefixtures("reuse_update_previews")
def test_publications_preserve_evidence_and_reversibly_project_immutable_logs(
    tmp_path: pathlib.Path,
) -> None:
    expected = 26
    assert (
        tests.formal.helpers.identity_transfer.check_publications(tmp_path) == expected
    )


@pytest.mark.usefixtures("reuse_update_previews")
def test_real_source_grouping_collapses_overlapping_aliases_before_publication(
    tmp_path: pathlib.Path,
) -> None:
    tests.formal.helpers.identity_transfer.check_grouped_publication(tmp_path)
