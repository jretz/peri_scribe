"""Checked validation paths preserve invalid intent and publish complete batches."""

import pathlib

import tests.formal.helpers.durable_updates


def test_recover_updates_matches_every_checked_validation_path(
    tmp_path: pathlib.Path,
) -> None:
    cases = tests.formal.helpers.durable_updates.cases(tmp_path / "tlc")
    for index, case in enumerate(cases):
        tests.formal.helpers.durable_updates.replay(
            case,
            tmp_path / str(index) / "2026",
        )
