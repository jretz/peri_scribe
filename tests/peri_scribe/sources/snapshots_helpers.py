"""Provide data builders and stand-ins for snapshots tests."""

from __future__ import annotations

import pathlib
import typing

import peri_scribe.sources.snapshots


if typing.TYPE_CHECKING:
    import pytest


def stub_directory(monkeypatch: pytest.MonkeyPatch, files: list[pathlib.Path]) -> None:
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
) -> peri_scribe.sources.snapshots.SourceFile:
    """Return a SourceFile with *serial_number* and *last_edit_timestamp*.

    Args:
        serial_number: The source file's serial number.
        last_edit_timestamp: The source file's last-edit timestamp.

    Returns:
        The constructed source file.
    """
    return peri_scribe.sources.snapshots.SourceFile(
        serial_number=serial_number,
        last_edit_timestamp=last_edit_timestamp,
    )


def deny_snapshot_listing(_self: pathlib.Path, _pattern: str) -> typing.Never:
    """Simulate denied access while enumerating source snapshots.

    Args:
        _self: Path receiving the intercepted filesystem operation.
        _pattern: Glob pattern accepted for directory-enumeration compatibility.

    Raises:
        PermissionError: Always, to exercise source-tree error handling.
    """
    message = "denied"
    raise PermissionError(message)
