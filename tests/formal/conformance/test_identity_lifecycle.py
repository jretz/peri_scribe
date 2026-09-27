"""All allocation phases and acknowledged histories share one checked lifecycle."""

import pathlib

import tests.formal.helpers.identity_lifecycle


def test_resolved_ownership_matches_complete_formal_resolver() -> None:
    tests.formal.helpers.identity_lifecycle.check_batches()


def test_prepare_updates_and_write_updates_preserve_ownership_across_publications(
    tmp_path: pathlib.Path,
) -> None:
    tests.formal.helpers.identity_lifecycle.check_publications(tmp_path)
