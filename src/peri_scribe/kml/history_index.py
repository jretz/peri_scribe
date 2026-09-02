"""Indexing a history layer's rows by fire so lookups avoid full scans.

Each history layer is scanned many times while KML geometry is built, once per fire, to
find the rows belonging to that fire. This module builds one compact index of row
positions up front, so each fire is answered with dictionary lookups and a small slice
instead of a boolean filter over the whole frame.
"""

from __future__ import annotations

import dataclasses
import itertools
import typing

import peri_scribe.geo.parsing


if typing.TYPE_CHECKING:
    import geopandas


@dataclasses.dataclass(frozen=True, kw_only=True)
class HistoryRowIndex:
    """Row positions of one history layer, keyed by fire identifier and by name.

    A row with a present identifier is indexed under both its identifier and its name; a
    row without one is indexed under its name only. The dual membership reproduces the
    history layers' original matching rules exactly: a fire with identifiers is matched
    by those identifiers alone, while a fire without identifiers is matched by every row
    sharing its name, including rows that carry an identifier.

    Keys are the raw column values, never string-coerced, so a lookup behaves the same
    as the original ``isin`` and equality filters (a non-string identifier never matches
    a string identifier, and a non-string name never matches a string name).

    Attributes:
        positions_by_identifier: Row positions keyed by their identifier value.
        positions_by_name: Row positions keyed by their name value.
    """

    positions_by_identifier: typing.Mapping[object, tuple[int, ...]]
    positions_by_name: typing.Mapping[object, tuple[int, ...]]

    @classmethod
    def from_frame(
        cls,
        frame: geopandas.GeoDataFrame,
    ) -> HistoryRowIndex:
        """Return an index of *frame*'s rows in one pass.

        Row positions are kept in ascending order, which is chronological order because
        the history layers store their rows oldest first.

        Args:
            frame: The history layer to index.

        Returns:
            The row positions keyed by identifier and by name.
        """
        by_identifier: dict[object, list[int]] = {}
        by_name: dict[object, list[int]] = {}
        for position, (identifier, name) in enumerate(
            zip(frame["fire_identifier"], frame["fire_name"], strict=True),
        ):
            if not peri_scribe.geo.parsing.is_missing(identifier):
                by_identifier.setdefault(identifier, []).append(position)
            if not peri_scribe.geo.parsing.is_missing(name):
                by_name.setdefault(name, []).append(position)
        return cls(
            positions_by_identifier={
                key: tuple(positions) for key, positions in by_identifier.items()
            },
            positions_by_name={
                key: tuple(positions) for key, positions in by_name.items()
            },
        )

    def positions_for(
        self,
        fire_identifiers: frozenset[str],
        entry_name: str,
    ) -> tuple[int, ...]:
        """Return the row positions belonging to one fire, in original order.

        A fire with identifiers is matched by those identifiers alone and never falls
        back to its name; a fire without identifiers is matched by its name. Each row
        carries at most one identifier, so merging identifier buckets cannot produce a
        duplicate position.

        Args:
            fire_identifiers: The fire's canonical identifier and aliases.
            entry_name: The fire's name, used only when it has no identifiers.

        Returns:
            The fire's row positions, ascending (chronological order).
        """
        if fire_identifiers:
            positions = itertools.chain.from_iterable(
                self.positions_by_identifier[identifier]
                for identifier in fire_identifiers
                if identifier in self.positions_by_identifier
            )
            return tuple(sorted(positions))
        return self.positions_by_name.get(entry_name, ())


def select_rows(
    frame: geopandas.GeoDataFrame,
    positions: tuple[int, ...],
) -> geopandas.GeoDataFrame:
    """Return the rows of *frame* at *positions* as a slice.

    The positions are integer row locations, so the slice preserves their order.

    Args:
        frame: The history layer to slice.
        positions: The row positions to keep, ascending.

    Returns:
        The selected rows, or an empty frame when *positions* is empty.
    """
    return frame.iloc[list(positions)]
