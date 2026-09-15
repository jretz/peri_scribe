"""Provide data builders and stand-ins for scores tests."""

from __future__ import annotations

import pathlib
import typing


if typing.TYPE_CHECKING:
    import peri_scribe.sources.external_sources


def make_external_output_path(
    *,
    tmp_path: pathlib.Path,
) -> typing.Callable[..., pathlib.Path]:
    """Create a callback to keep external-source reads inside the test directory.

    Args:
        tmp_path: Isolated directory used by the callback.

    Returns:
        The callback bound to the supplied dependencies.
    """

    def output_path(
        _year_directory: pathlib.Path,
        source: peri_scribe.sources.external_sources.ExternalSource,
        **_keywords: object,
    ) -> pathlib.Path:
        """Keep external-source reads inside the test directory.

        Args:
            _year_directory: Unused production year directory.
            source: The source whose storage format determines the suffix.
            _keywords: Unused source path options.

        Returns:
            The isolated SQLite or GeoPackage source path.
        """
        suffix = ".sqlite" if source.compact_database else ".gpkg"
        return tmp_path / "sources" / source.name / f"{source.name}{suffix}"

    return output_path
