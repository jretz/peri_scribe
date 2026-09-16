"""Replace main source dependencies with controlled test doubles."""

from __future__ import annotations

import pathlib
import typing


def make_fetch_recorder(
    *,
    fetched: list[tuple[object, pathlib.Path]],
) -> typing.Callable[..., tuple[pathlib.Path, ...]]:
    """Create a callback to capture the source and directory selected by the CLI.

    Args:
        fetched: Shared list recording source selections and destination directories.

    Returns:
        The callback bound to the supplied dependencies.
    """

    def fetch_external_source(
        source_arg: object,
        directory: pathlib.Path,
    ) -> tuple[pathlib.Path, ...]:
        """Capture the source and directory selected by the CLI.

        Args:
            source_arg: External source selected by the CLI.
            directory: Directory supplied to the intercepted storage operation.

        Returns:
            The synthetic output path returned by the fetch stub.
        """
        fetched.append((source_arg, directory))
        return (pathlib.Path("/out.gpkg"),)

    return fetch_external_source
