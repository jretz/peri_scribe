"""Relative source strings preserve lexical behavior and remain caller-owned."""

from __future__ import annotations

import pathlib

import pytest

import peri_scribe.sources.provenance
import tests.helpers.doubles.peri_scribe.sources.provenance


@pytest.mark.parametrize(
    ("path", "directory"),
    [
        (pathlib.Path("/sources/feed/fire.gpkg"), pathlib.Path("/sources")),
        (pathlib.PurePosixPath("feed/../fire.gpkg"), pathlib.PurePosixPath("feed")),
        (pathlib.PurePosixPath("feed/火,\\u0000.gpkg"), pathlib.PurePosixPath("feed")),
        (
            pathlib.PureWindowsPath("C:/FEED/fire.gpkg"),
            pathlib.PureWindowsPath("c:/feed"),
        ),
        (pathlib.PurePosixPath("/sources"), pathlib.PurePosixPath("/sources")),
    ],
)
def test_source_paths_relative_preserves_exact_lexical_string(
    path: pathlib.PurePath,
    directory: pathlib.PurePath,
) -> None:
    source_paths = peri_scribe.sources.provenance.SourcePaths(directory=directory)
    expected = str(path.relative_to(directory))
    assert source_paths.relative(path) == expected
    assert source_paths.relative(path) == expected
    assert source_paths.relative_paths == {(type(path), str(path)): expected}


@pytest.mark.parametrize(
    "directory",
    [
        pathlib.PureWindowsPath("C:/Root"),
        pathlib.PureWindowsPath("c:/ROOT"),
        pathlib.PureWindowsPath("C:/"),
    ],
)
def test_source_paths_relative_preserves_windows_case_with_equal_path_keys(
    directory: pathlib.PureWindowsPath,
) -> None:
    source_paths = peri_scribe.sources.provenance.SourcePaths(directory=directory)
    paths = (
        pathlib.PureWindowsPath("C:/Root/A.gpkg"),
        pathlib.PureWindowsPath("c:/root/a.gpkg"),
    )
    assert paths[0] == paths[1]
    for path in (*paths, *reversed(paths)):
        assert source_paths.relative(path) == str(path.relative_to(directory))
    assert len(source_paths.relative_paths) == len(paths)


def test_for_directory_preserves_exact_windows_root_spelling() -> None:
    retained = peri_scribe.sources.provenance.SourcePaths(
        directory=pathlib.PureWindowsPath("C:/Root"),
    )
    for directory in (
        pathlib.PureWindowsPath("c:/Root"),
        pathlib.PureWindowsPath("C:/ROOT"),
        pathlib.PureWindowsPath("D:/Root"),
        pathlib.PureWindowsPath("C:/"),
    ):
        selected = peri_scribe.sources.provenance.for_directory(directory, retained)
        assert selected is not retained
        assert str(selected.directory) == str(directory)


def test_source_paths_relative_propagates_errors_without_retaining_them() -> None:
    source_paths = peri_scribe.sources.provenance.SourcePaths(
        directory=pathlib.Path("/sources"),
    )
    for _ in range(2):
        with pytest.raises(ValueError, match="not in the subpath"):
            source_paths.relative(pathlib.Path("/outside/fire.gpkg"))
    assert not source_paths.relative_paths


def test_source_paths_relative_rechecks_custom_path_behavior() -> None:
    source_paths = peri_scribe.sources.provenance.SourcePaths(
        directory=pathlib.Path("/sources"),
    )
    path = tests.helpers.doubles.peri_scribe.sources.provenance.ChangingPath(
        "/sources/fire.gpkg",
    )
    assert source_paths.relative(path) == "first"
    path.result = "corrected"
    assert source_paths.relative(path) == "corrected"
    assert not source_paths.relative_paths


def test_source_paths_relative_rejects_metaclass_stock_equality_spoof() -> None:
    source_paths = peri_scribe.sources.provenance.SourcePaths(
        directory=pathlib.Path("/sources"),
    )
    path = tests.helpers.doubles.peri_scribe.sources.provenance.StockEqualPath(
        "/sources/fire.gpkg",
    )
    assert type(path) in peri_scribe.sources.provenance.IMMUTABLE_PATH_TYPES
    assert source_paths.relative(path) == "first"
    path.result = "corrected"
    assert source_paths.relative(path) == "corrected"
    assert not source_paths.relative_paths


def test_source_paths_relative_rejects_metaclass_directory_spoof() -> None:
    directory = tests.helpers.doubles.peri_scribe.sources.provenance.StockEqualPath(
        "/sources",
    )
    source_paths = peri_scribe.sources.provenance.SourcePaths(directory=directory)
    path = pathlib.Path("/sources/fire.gpkg")
    assert source_paths.relative(path) == str(path.relative_to(directory))
    assert source_paths.relative(path) == str(path.relative_to(directory))
    assert not source_paths.relative_paths


@pytest.mark.parametrize(
    "directory_type",
    [
        tests.helpers.doubles.peri_scribe.sources.provenance.ChangingPath,
        tests.helpers.doubles.peri_scribe.sources.provenance.StockEqualPath,
    ],
)
def test_for_directory_preserves_custom_root_instance_state(
    directory_type: type[
        tests.helpers.doubles.peri_scribe.sources.provenance.ChangingPath
    ],
) -> None:
    old = directory_type("/sources")
    current = directory_type("/sources")
    old.result = "previous"
    current.result = "current"
    assert str(old) == str(current)
    assert type(old) is type(current)
    retained = peri_scribe.sources.provenance.SourcePaths(directory=old)
    selected = peri_scribe.sources.provenance.for_directory(current, retained)
    assert selected.directory is current
    path = tests.helpers.doubles.peri_scribe.sources.provenance.DirectoryAwarePath(
        "/sources/fire.gpkg",
    )
    assert selected.relative(path) == "current"


def test_for_directory_does_not_substitute_metaclass_equal_stock_root() -> None:
    directory = tests.helpers.doubles.peri_scribe.sources.provenance.StockEqualPath(
        "/sources",
    )
    retained = peri_scribe.sources.provenance.SourcePaths(
        directory=pathlib.Path("/sources"),
    )
    assert type(directory) is not type(retained.directory)
    selected = peri_scribe.sources.provenance.for_directory(directory, retained)
    assert selected.directory is directory


def test_source_paths_relative_does_not_memoize_custom_directory() -> None:
    directory = tests.helpers.doubles.peri_scribe.sources.provenance.CustomDirectory(
        "/sources",
    )
    source_paths = peri_scribe.sources.provenance.SourcePaths(directory=directory)
    path = pathlib.Path("/sources/fire.gpkg")
    assert source_paths.relative(path) == str(path.relative_to(directory))
    assert source_paths.relative(path) == str(path.relative_to(directory))
    assert not source_paths.relative_paths


def test_for_directory_keeps_distinct_roots_and_custom_types_separate() -> None:
    directory = pathlib.Path("/sources")
    retained = peri_scribe.sources.provenance.SourcePaths(directory=directory)
    assert peri_scribe.sources.provenance.for_directory(directory, retained) is retained
    other = peri_scribe.sources.provenance.for_directory(directory.parent, retained)
    assert other is not retained
    assert other.directory == directory.parent
    custom = tests.helpers.doubles.peri_scribe.sources.provenance.CustomDirectory(
        directory,
    )
    assert (
        peri_scribe.sources.provenance.for_directory(custom, retained) is not retained
    )
    fresh = peri_scribe.sources.provenance.for_directory(directory, None)
    assert fresh is not retained
    assert fresh.directory == directory


def test_source_paths_keep_independent_caller_owned_memos() -> None:
    first = peri_scribe.sources.provenance.SourcePaths(directory=pathlib.Path("feed"))
    second = peri_scribe.sources.provenance.SourcePaths(directory=pathlib.Path("feed"))
    first.relative(pathlib.Path("feed/fire.gpkg"))
    assert not second.relative_paths
