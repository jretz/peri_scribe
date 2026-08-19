"""Tests for peri_scribe.snapshots."""

from __future__ import annotations

import pathlib
import re
import typing

import pytest

import peri_scribe.snapshots


def stub_directory(
    monkeypatch: pytest.MonkeyPatch,
    files: list[pathlib.Path],
) -> None:
    """Point Path.is_dir and iterdir at the given files.

    Args:
        monkeypatch: The monkeypatch fixture.
        files: The directory's contents.
    """
    monkeypatch.setattr(pathlib.Path, "is_dir", lambda _self: True)
    monkeypatch.setattr(pathlib.Path, "iterdir", lambda _self: iter(files))


def test_existing_geopackage_filenames_returns_empty_list_without_directory(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(pathlib.Path, "is_dir", lambda _self: False)
    assert (
        peri_scribe.snapshots.existing_geopackage_filenames(
            pathlib.Path("/missing"),
        )
        == []
    )


def test_geo_package_files_returns_nested_files_in_sorted_order(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    directory = pathlib.Path("/data")
    alpha = directory / "sources" / "Alpha_0"
    beta = directory / "sources" / "Beta_0"
    files = [
        beta / "000000,lastEdit=c.gpkg",
        alpha / "000002,lastEdit=b.gpkg",
        alpha / "000001,lastEdit=a.gpkg",
    ]
    monkeypatch.setattr(pathlib.Path, "is_dir", lambda _self: True)
    monkeypatch.setattr(
        pathlib.Path,
        "rglob",
        lambda _self, _pattern: iter(files),
    )
    assert peri_scribe.snapshots.geo_package_files(directory) == [
        alpha / "000001,lastEdit=a.gpkg",
        alpha / "000002,lastEdit=b.gpkg",
        beta / "000000,lastEdit=c.gpkg",
    ]


def test_geo_package_files_returns_empty_list_without_directory(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(pathlib.Path, "is_dir", lambda _self: False)
    assert peri_scribe.snapshots.geo_package_files(pathlib.Path("/missing")) == []


def test_geo_package_files_raises_system_exit_when_tree_cannot_be_read(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    directory = pathlib.Path("/data")

    def fake_rglob(_self: pathlib.Path, _pattern: str) -> typing.Never:
        message = "denied"
        raise PermissionError(message)

    monkeypatch.setattr(pathlib.Path, "is_dir", lambda _self: True)
    monkeypatch.setattr(pathlib.Path, "rglob", fake_rglob)
    with pytest.raises(
        SystemExit,
        match=re.escape(f"Failed to read {directory}: denied"),
    ):
        peri_scribe.snapshots.geo_package_files(directory)


def test_source_geopackage_path_places_watermark_file_under_source_directory() -> None:
    path = peri_scribe.snapshots.source_geopackage_path(
        pathlib.Path("/base"),
        2026,
        "CA_Perimeters_NIFC_FIRIS_public_view_0",
        17,
        "lastEdit=abc123",
    )
    assert path == pathlib.Path(
        "/base/data/2026/sources/CA_Perimeters_NIFC_FIRIS_public_view_0/"
        "000017,lastEdit=abc123.gpkg",
    )


def test_geopackage_filename_zero_pads_serial_number() -> None:
    assert peri_scribe.snapshots.geopackage_filename(
        17,
        "lastEdit=abc123",
    ) == pathlib.Path("000017,lastEdit=abc123.gpkg")


def test_parse_geopackage_filename_returns_serial_and_watermark() -> None:
    assert peri_scribe.snapshots.parse_geopackage_filename(
        pathlib.Path("000017,lastEdit=abc,def.gpkg"),
    ) == (17, "lastEdit=abc,def")


def test_next_serial_number_starts_at_zero_without_existing_files() -> None:
    expected_serial_number = 0
    assert (
        peri_scribe.snapshots.next_serial_number([], "lastEdit=abc123")
        == expected_serial_number
    )


def test_next_serial_number_increments_beyond_largest_serial() -> None:
    expected_serial_number = 4
    assert (
        peri_scribe.snapshots.next_serial_number(
            [pathlib.Path("000003,lastEdit=abc123.gpkg")],
            "lastEdit=def456",
        )
        == expected_serial_number
    )


def test_next_serial_number_reuses_serial_for_existing_watermark() -> None:
    expected_serial_number = 3
    assert (
        peri_scribe.snapshots.next_serial_number(
            [pathlib.Path("000003,lastEdit=abc123.gpkg")],
            "lastEdit=abc123",
        )
        == expected_serial_number
    )


def test_next_serial_number_ignores_malformed_filenames() -> None:
    expected_serial_number = 3
    assert (
        peri_scribe.snapshots.next_serial_number(
            [
                pathlib.Path("old-style.gpkg"),
                pathlib.Path("000002,lastEdit=abc123.gpkg"),
            ],
            "lastEdit=def456",
        )
        == expected_serial_number
    )


def test_snapshot_path_for_watermark_returns_matching_path(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    directory = pathlib.Path("/sources/CA_Perimeters_NIFC_FIRIS_public_view_0")
    stub_directory(
        monkeypatch,
        [
            directory / "000017,lastEdit=abc123.gpkg",
            directory / "000018,lastEdit=def789.gpkg",
        ],
    )
    assert (
        peri_scribe.snapshots.snapshot_path_for_watermark(
            directory,
            "lastEdit=abc123",
        )
        == directory / "000017,lastEdit=abc123.gpkg"
    )


def test_snapshot_path_for_watermark_returns_none_without_match(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    directory = pathlib.Path("/sources/CA_Perimeters_NIFC_FIRIS_public_view_0")
    stub_directory(monkeypatch, [directory / "000017,lastEdit=abc123.gpkg"])
    assert (
        peri_scribe.snapshots.snapshot_path_for_watermark(
            directory,
            "lastEdit=other",
        )
        is None
    )


def test_snapshot_path_for_watermark_ignores_malformed_filenames(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    directory = pathlib.Path("/sources/CA_Perimeters_NIFC_FIRIS_public_view_0")
    stub_directory(monkeypatch, [directory / "old-style.gpkg"])
    assert (
        peri_scribe.snapshots.snapshot_path_for_watermark(
            directory,
            "lastEdit=abc123",
        )
        is None
    )


def test_year_directory_path_groups_year_under_data() -> None:
    assert peri_scribe.snapshots.year_directory_path(
        pathlib.Path("/base"),
        2026,
    ) == pathlib.Path("/base/data/2026")


def test_sources_directory_path_places_sources_under_year() -> None:
    assert peri_scribe.snapshots.sources_directory_path(
        pathlib.Path("/data/2026"),
    ) == pathlib.Path("/data/2026/sources")


def test_fire_index_path_places_index_in_sources_directory() -> None:
    assert peri_scribe.snapshots.fire_index_path(
        pathlib.Path("/data/2026"),
    ) == pathlib.Path("/data/2026/sources/fires.json")
