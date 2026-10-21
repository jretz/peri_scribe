"""Retained history identities preserve the complete declared cache dependency."""

import pathlib

import pytest

import tests.formal.helpers.prepared_history_identity


@pytest.mark.parametrize("change", ["measurement", "order", "units", "record"])
@pytest.mark.parametrize("retained", [True, False])
def test_history_digest_guards_preserve_complete_description_dependencies(
    tmp_path: pathlib.Path,
    change: str,
    *,
    retained: bool,
) -> None:
    tests.formal.helpers.prepared_history_identity.compare(
        tmp_path,
        change,
        retained=retained,
    )
