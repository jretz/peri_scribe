"""Observers and generators share stable year and output locations."""

import pathlib

import peri_scribe.paths


def test_kmz_filename_names_year() -> None:
    assert peri_scribe.paths.kmz_filename(2026) == "PeriScribe Fires 2026.kmz"


def test_kmz_path_places_file_in_maps_directory() -> None:
    assert peri_scribe.paths.kmz_path(pathlib.Path("data/2026")) == (
        pathlib.Path("data/2026/maps/PeriScribe Fires 2026.kmz")
    )


def test_markdown_report_path_names_year() -> None:
    assert peri_scribe.paths.markdown_report_path(
        pathlib.Path("data/2026"),
    ) == pathlib.Path("data/2026/reports/PeriScribe Fires 2026.md")


def test_year_directory_path_groups_year_under_data() -> None:
    assert peri_scribe.paths.year_directory_path(
        pathlib.Path("/base"),
        2026,
    ) == pathlib.Path("/base/data/2026")


def test_year_for_year_directory_returns_directory_name_as_year() -> None:
    expected_year = 2026
    assert (
        peri_scribe.paths.year_for_year_directory(
            pathlib.Path(f"/base/data/{expected_year}"),
        )
        == expected_year
    )
