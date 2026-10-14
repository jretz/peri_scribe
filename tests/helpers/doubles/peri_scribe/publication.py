"""Replace publication dependencies with controlled test doubles."""

from __future__ import annotations

import datetime
import pathlib
import typing

import tests.helpers.factories.peri_scribe.publication


if typing.TYPE_CHECKING:
    import peri_scribe.publication


def make_snapshot_measurement_recorder(
    *,
    reads: list[pathlib.Path],
) -> typing.Callable[..., tuple[peri_scribe.publication.Mapping, ...]]:
    """Return a recorder of snapshot reads that keeps inventory and cache I/O real.

    Args:
        reads: Shared list recording expensive snapshot measurements.

    Returns:
        The callback bound to the supplied dependencies.
    """

    def measure(
        path: pathlib.Path,
        _sources: pathlib.Path,
        captured: datetime.datetime,
    ) -> tuple[peri_scribe.publication.Mapping, ...]:
        """Record expensive reads while exercising real inventory and cache I/O.

        Args:
            path: The source snapshot whose measurement request is recorded.
            _sources: The sources root accepted to match the reader's signature; unused.
            captured: The actual capture time supplied by collection.

        Returns:
            A tuple containing one source observation with the collection timestamp.
        """
        reads.append(path)
        return (
            tests.helpers.factories.peri_scribe.publication.mapping(
                100,
                captured_at=captured,
            ),
        )

    return measure
