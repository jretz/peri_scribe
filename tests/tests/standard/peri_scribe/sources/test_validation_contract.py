"""Validation cannot certify ambiguous features or unknown geographic meaning."""

import pytest

import peri_scribe.sources.validation
import tests.helpers.factories.peri_scribe.sources.changes
import tests.helpers.factories.peri_scribe.sources.feed_types


@pytest.mark.parametrize("reference", [None, 3857])
def test_validate_feed_rejects_identical_coordinates_with_incompatible_crs(
    reference: int | None,
) -> None:
    complete = tests.helpers.factories.peri_scribe.sources.changes.change_dataframe([
        (1, "a", (1.0, 1.0)),
    ])
    stored = complete.set_crs(reference, allow_override=True)
    result = peri_scribe.sources.validation.validate_feed(
        tests.helpers.factories.peri_scribe.sources.feed_types.change_feed(),
        complete,
        stored,
    )
    assert result.has_problems


@pytest.mark.parametrize("empty", [False, True])
def test_validate_feed_rejects_unknown_crs_even_when_both_frames_agree(
    *,
    empty: bool,
) -> None:
    complete = tests.helpers.factories.peri_scribe.sources.changes.change_dataframe(
        [] if empty else [(1, "a", (1.0, 1.0))],
    )
    complete.set_crs(None, allow_override=True, inplace=True)
    result = peri_scribe.sources.validation.validate_feed(
        tests.helpers.factories.peri_scribe.sources.feed_types.change_feed(),
        complete,
        complete,
    )
    assert result.has_problems


@pytest.mark.parametrize("stored_duplicate", [False, True])
@pytest.mark.parametrize("different", [False, True])
def test_validate_feed_rejects_duplicate_ids_even_if_last_row_matches(
    *,
    stored_duplicate: bool,
    different: bool,
) -> None:
    row = (1, "a", (1.0, 1.0))
    duplicate = tests.helpers.factories.peri_scribe.sources.changes.change_dataframe([
        (1, "changed", (2.0, 2.0)) if different else row,
        row,
    ])
    single = tests.helpers.factories.peri_scribe.sources.changes.change_dataframe([row])
    result = peri_scribe.sources.validation.validate_feed(
        tests.helpers.factories.peri_scribe.sources.feed_types.change_feed(),
        single if stored_duplicate else duplicate,
        duplicate if stored_duplicate else single,
    )
    assert result.has_problems


def test_validate_feed_rejects_duplicates_in_extra_stored_features() -> None:
    complete = tests.helpers.factories.peri_scribe.sources.changes.change_dataframe([
        (1, "a", (1.0, 1.0)),
    ])
    stored = tests.helpers.factories.peri_scribe.sources.changes.change_dataframe([
        (1, "a", (1.0, 1.0)),
        (2, "b", (2.0, 2.0)),
        (2, "b", (2.0, 2.0)),
    ])
    result = peri_scribe.sources.validation.validate_feed(
        tests.helpers.factories.peri_scribe.sources.feed_types.change_feed(),
        complete,
        stored,
    )
    assert result.has_problems
