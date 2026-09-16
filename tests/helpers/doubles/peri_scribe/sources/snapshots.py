"""Replace snapshots dependencies with controlled test doubles."""

from __future__ import annotations

import pathlib
import typing


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
