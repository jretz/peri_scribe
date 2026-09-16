"""Replace scores dependencies with controlled test doubles."""

from __future__ import annotations

import dataclasses
import pathlib
import typing


if typing.TYPE_CHECKING:
    import peri_scribe.models

if typing.TYPE_CHECKING:
    import peri_scribe.sources.external_data


@dataclasses.dataclass(frozen=True, kw_only=True)
class ScoreFiresStubs:
    """The documents score_fires wrote and the CCDF writes it made."""

    writes: list[tuple[pathlib.Path, peri_scribe.models.FireScores]]
    ccdf_writes: list[tuple[pathlib.Path, peri_scribe.models.FireScores]]


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
        source: peri_scribe.sources.external_data.ExternalSource,
        **kwargs: object,
    ) -> pathlib.Path:
        """Keep external-source reads inside the test directory.

        Args:
            _year_directory: Unused production year directory.
            source: The source whose storage format determines the suffix.
            kwargs: Unused source path options.

        Returns:
            The isolated SQLite or GeoPackage source path.
        """
        suffix = ".sqlite" if source.compact_database else ".gpkg"
        return tmp_path / "sources" / source.name / f"{source.name}{suffix}"

    return output_path
