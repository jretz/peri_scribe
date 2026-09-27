"""A successful source audit establishes unambiguous spatial content coverage."""

import tests.formal.helpers.source_validation


def test_validate_feed_matches_checked_relational_coverage_and_diagnostics() -> None:
    expected = 3249
    assert tests.formal.helpers.source_validation.check_frames() == expected


def test_validate_feed_missing_store_matches_checked_absent_schema() -> None:
    expected = 114
    assert tests.formal.helpers.source_validation.check_missing_store() == expected
