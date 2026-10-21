"""Carry exact relative source strings with the preparation that consumes them.

[Preparation reasoning](../../../docs/algorithms/source-index-preparation.md)
"""

from __future__ import annotations

import dataclasses
import pathlib


IMMUTABLE_PATH_TYPES = (
    pathlib.PosixPath,
    pathlib.PurePosixPath,
    pathlib.WindowsPath,
    pathlib.PureWindowsPath,
)


def is_stock_path(path: pathlib.PurePath) -> bool:
    """Recognize immutable stock classes without invoking custom metaclass equality.

    Args:
        path: The path whose lexical behavior could be retained.

    Returns:
        Whether its class has ordinary identity equality and is a stock Path class.
    """
    path_type = type(path)
    return type(path_type) is type and path_type in IMMUTABLE_PATH_TYPES


@dataclasses.dataclass(frozen=True, kw_only=True)
class SourcePaths:
    """Retain lexical strings for one source root without retaining filesystem evidence.

    The owning source read and its groups share this value. Releasing them releases
    the memo. Exact stock paths are immutable; custom subclasses use their own current
    relative_to behavior on every call. Exceptions are propagated without retention.
    Consumers treat relative_paths as read-only; only relative adds derived strings.
    """

    directory: pathlib.PurePath
    relative_paths: dict[tuple[type[pathlib.PurePath], str], str] = dataclasses.field(
        default_factory=dict,
        compare=False,
        repr=False,
    )

    def relative(self, path: pathlib.PurePath) -> str:
        """Preserve Path.relative_to lexical behavior while sharing repeated results.

        Args:
            path: The source path whose provenance is being consumed.

        Returns:
            The exact relative_to string; its original errors propagate unchanged.
        """
        if not is_stock_path(path) or not is_stock_path(self.directory):
            return str(path.relative_to(self.directory))
        key = type(path), str(path)
        try:
            return self.relative_paths[key]
        except KeyError:
            value = str(path.relative_to(self.directory))
            self.relative_paths[key] = value
            return value


def for_directory(
    directory: pathlib.PurePath,
    retained: SourcePaths | None,
) -> SourcePaths:
    """Reuse a memo for the same stock lexical root, preserving custom root objects.

    Args:
        directory: The caller's current lexical provenance root.
        retained: A memo carried by complete or selective source preparation.

    Returns:
        That matching memo, or a new caller-owned memo for the supplied directory.
    """
    if (
        retained is not None
        and type(retained.directory) is type(directory)
        and is_stock_path(directory)
        and str(retained.directory) == str(directory)
    ):
        return retained
    return SourcePaths(directory=directory)
