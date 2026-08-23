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
    """Point Path.is_dir and rglob at the given files.

    Args:
        monkeypatch: The monkeypatch fixture.
        files: The directory's contents.
    """
    monkeypatch.setattr(pathlib.Path, "is_dir", lambda _self: True)
    monkeypatch.setattr(pathlib.Path, "rglob", lambda _self, _pattern: iter(files))


def source_file(
    *,
    serial_number: int,
    last_edit_timestamp: int = 0,
) -> peri_scribe.snapshots.SourceFile:
    """Return a SourceFile with *serial_number* and *last_edit_timestamp*.

    Args:
        serial_number: The source file's serial number.
        last_edit_timestamp: The source file's last-edit timestamp.

    Returns:
        The constructed source file.
    """
    return peri_scribe.snapshots.SourceFile(
        serial_number=serial_number,
        last_edit_timestamp=last_edit_timestamp,
    )


def test_source_file_relative_path_places_file_in_bucket_directory() -> None:
    assert source_file(
        serial_number=2037,
        last_edit_timestamp=1787118540625,
    ).relative_path == pathlib.Path("002___/002037,lastEdit=1787118540625.gpkg")


def test_source_file_relative_path_buckets_by_thousands() -> None:
    assert source_file(serial_number=999).relative_path == pathlib.Path(
        "000___/000999,lastEdit=0.gpkg",
    )
    assert source_file(serial_number=1000).relative_path == pathlib.Path(
        "001___/001000,lastEdit=0.gpkg",
    )


def test_source_file_from_path_parses_serial_and_timestamp() -> None:
    assert peri_scribe.snapshots.SourceFile.from_path(
        pathlib.Path("002___/002037,lastEdit=1787118540625.gpkg"),
    ) == source_file(
        serial_number=2037,
        last_edit_timestamp=1787118540625,
    )


def test_source_file_from_path_rejects_unrecognized_timestamp() -> None:
    with pytest.raises(ValueError, match="Unrecognized snapshot filename"):
        peri_scribe.snapshots.SourceFile.from_path(
            pathlib.Path("000001,soon.gpkg"),
        )


def test_source_file_from_path_rejects_missing_timestamp() -> None:
    with pytest.raises(ValueError, match="Unrecognized snapshot filename"):
        peri_scribe.snapshots.SourceFile.from_path(pathlib.Path("000001.gpkg"))


def test_next_serial_number_starts_at_zero_without_existing_files() -> None:
    assert peri_scribe.snapshots.next_serial_number([], 123) == 0


def test_next_serial_number_increments_beyond_largest_serial() -> None:
    expected_serial_number = 4
    assert (
        peri_scribe.snapshots.next_serial_number(
            [source_file(serial_number=3, last_edit_timestamp=123)],
            456,
        )
        == expected_serial_number
    )


def test_next_serial_number_reuses_serial_for_existing_timestamp() -> None:
    expected_serial_number = 3
    assert (
        peri_scribe.snapshots.next_serial_number(
            [source_file(serial_number=3, last_edit_timestamp=123)],
            123,
        )
        == expected_serial_number
    )


def test_existing_source_files_returns_empty_without_directory(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(pathlib.Path, "is_dir", lambda _self: False)
    assert peri_scribe.snapshots.existing_source_files(pathlib.Path("/missing")) == []


def test_existing_source_files_returns_source_files_sorted_by_serial(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    directory = pathlib.Path("/sources/feed")
    files = [
        directory / "001___" / "001003,lastEdit=3.gpkg",
        directory / "000___" / "000002,lastEdit=2.gpkg",
        directory / "000___" / "000001,lastEdit=1.gpkg",
    ]
    stub_directory(monkeypatch, files)
    assert peri_scribe.snapshots.existing_source_files(directory) == [
        source_file(serial_number=1, last_edit_timestamp=1),
        source_file(serial_number=2, last_edit_timestamp=2),
        source_file(serial_number=1003, last_edit_timestamp=3),
    ]


def test_existing_source_files_ignores_malformed_filenames(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    directory = pathlib.Path("/sources/feed")
    files = [
        directory / "000___" / "000001,lastEdit=1.gpkg",
        directory / "old-style.gpkg",
    ]
    stub_directory(monkeypatch, files)
    assert peri_scribe.snapshots.existing_source_files(directory) == [
        source_file(serial_number=1, last_edit_timestamp=1),
    ]


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


def test_source_geopackage_path_places_file_under_source_directory() -> None:
    path = peri_scribe.snapshots.source_geopackage_path(
        pathlib.Path("/base"),
        2026,
        "CA_Perimeters_NIFC_FIRIS_public_view_0",
        source_file(serial_number=17, last_edit_timestamp=123),
    )
    assert path == pathlib.Path(
        "/base/data/2026/sources/CA_Perimeters_NIFC_FIRIS_public_view_0/"
        "000___/000017,lastEdit=123.gpkg",
    )


def test_snapshot_path_for_last_edit_timestamp_returns_matching_path(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    directory = pathlib.Path("/sources/CA_Perimeters_NIFC_FIRIS_public_view_0")
    stub_directory(
        monkeypatch,
        [
            directory / "000___" / "000017,lastEdit=123.gpkg",
            directory / "000___" / "000018,lastEdit=789.gpkg",
        ],
    )
    assert (
        peri_scribe.snapshots.snapshot_path_for_last_edit_timestamp(directory, 123)
        == directory / "000___" / "000017,lastEdit=123.gpkg"
    )


def test_snapshot_path_for_last_edit_timestamp_returns_none_without_match(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    directory = pathlib.Path("/sources/CA_Perimeters_NIFC_FIRIS_public_view_0")
    stub_directory(
        monkeypatch,
        [directory / "000___" / "000017,lastEdit=123.gpkg"],
    )
    assert (
        peri_scribe.snapshots.snapshot_path_for_last_edit_timestamp(directory, 999)
        is None
    )


def test_source_directory_path_places_source_under_sources() -> None:
    assert peri_scribe.snapshots.source_directory_path(
        pathlib.Path("/base"),
        2026,
        "Feed_0",
    ) == pathlib.Path("/base/data/2026/sources/Feed_0")


def test_source_name_from_snapshot_path_returns_feed_directory_name() -> None:
    assert (
        peri_scribe.snapshots.source_name_from_snapshot_path(
            pathlib.Path("sources/Feed_0/000___/000000,lastEdit=0.gpkg"),
        )
        == "Feed_0"
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
