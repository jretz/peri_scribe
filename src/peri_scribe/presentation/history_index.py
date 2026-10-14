"""Index a history layer's rows by fire so lookups avoid full scans.

Building KML requires the history rows for each fire. One pass through the layer builds
a compact index of row positions, so later requests use dictionary lookups and a small
slice without scanning unrelated rows again.

[Algorithm note](../../../docs/algorithms/presentation-selection.md)
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
    """Index one history layer's rows by fire identifier, name, and component.

    A stored component identity selects exactly one source group. Legacy histories use
    identifiers and names: identified fires match their aliases, while anonymous fires
    match all rows with the same name.

    Keys retain their original types so lookup agrees with ``isin`` and equality
    filters. Converting them to strings could make a numeric identifier or name match a
    string with the same spelling.

    Attributes:
        positions_by_identifier: Row positions keyed by their identifier value.
        positions_by_name: Row positions keyed by their name value.
        positions_by_component: Exact source-component positions when recorded.
    """

    positions_by_identifier: typing.Mapping[object, tuple[int, ...]]
    positions_by_name: typing.Mapping[object, tuple[int, ...]]
    positions_by_component: typing.Mapping[object, tuple[int, ...]] = dataclasses.field(
        default_factory=dict,
    )

    @classmethod
    def from_frame(cls, frame: geopandas.GeoDataFrame) -> HistoryRowIndex:
        """Return an index of *frame*'s rows in one pass.

        Row positions are kept in ascending order, which is chronological order because
        the history layers store their rows oldest first.

        Args:
            frame: The history layer to index.

        Returns:
            The row positions keyed by identifier, name, and source component.
        """
        by_identifier: dict[object, list[int]] = {}
        by_name: dict[object, list[int]] = {}
        by_component: dict[object, list[int]] = {}
        for position, (identifier, name, component) in enumerate(
            zip(
                frame["fire_identifier"],
                frame["fire_name"],
                frame.get("fire_component_id", [None] * len(frame)),
                strict=True,
            ),
        ):
            if not peri_scribe.geo.parsing.is_missing(component):
                by_component.setdefault(component, []).append(position)
            if not peri_scribe.geo.parsing.is_missing(identifier):
                by_identifier.setdefault(identifier, []).append(position)
            if not peri_scribe.geo.parsing.is_missing(name):
                by_name.setdefault(name, []).append(position)
        return cls(
            positions_by_identifier={
                key: tuple(positions) for key, positions in by_identifier.items()
            },
            positions_by_component={
                key: tuple(positions) for key, positions in by_component.items()
            },
            positions_by_name={
                key: tuple(positions) for key, positions in by_name.items()
            },
        )

    def positions_for(
        self,
        fire_identifiers: frozenset[str],
        entry_name: str,
        component_id: str | None = None,
    ) -> tuple[int, ...]:
        """Return the row positions belonging to one fire, in original order.

        A stored component selects its exact rows. Entries without a component retain
        identifier-only selection when identified and the legacy name fallback when
        anonymous. Merging identifier buckets cannot duplicate a row position.

        Args:
            fire_identifiers: The fire's canonical identifier and aliases.
            entry_name: The fire's name, used only when it has no identifiers.
            component_id: Its exact source group, when recorded in derived history.

        Returns:
            The fire's row positions, ascending (chronological order).
        """
        if component_id is not None:
            return self.positions_by_component.get(component_id, ())
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
