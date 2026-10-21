"""Sparse KMZ evidence agrees with the independently checked preparation contract."""

import pathlib

import tests.formal.helpers.kmz_preparation


def test_latest_positions_match_checked_demand_definition() -> None:
    tests.formal.helpers.kmz_preparation.check_latest_positions()


def test_read_projected_layer_preserves_checked_latest_values(
    tmp_path: pathlib.Path,
) -> None:
    tests.formal.helpers.kmz_preparation.check_projected_values(tmp_path)


def test_qualifying_histories_preserves_checked_subset() -> None:
    tests.formal.helpers.kmz_preparation.check_qualifying_histories()


def test_preparation_key_rejects_each_changed_dependency(
    tmp_path: pathlib.Path,
) -> None:
    tests.formal.helpers.kmz_preparation.check_preparation_identity(tmp_path)
