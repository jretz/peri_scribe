"""Share immutable source columns while selecting each fire by row position.

[Selection contract](../../docs/algorithms/presentation-selection.md)
"""

from __future__ import annotations

import dataclasses
import types
import typing


if typing.TYPE_CHECKING:
    import pandas as pd


type Frame = pd.DataFrame | HistoryRows
type Row = pd.Series | HistoryRow
type Source = pd.DataFrame | HistoryColumns


@dataclasses.dataclass(frozen=True, kw_only=True, slots=True)
class HistoryColumns:
    """Retain source scalars once while many fires select disjoint row positions.

    Tuples protect column structure; contained values, including geometries and source
    attribute dictionaries, are borrowed and must remain unchanged during preparation.
    """

    fields: typing.Mapping[str, tuple[object, ...]]

    @classmethod
    def from_frame(cls, frame: pd.DataFrame) -> HistoryColumns:
        """Materialize each named source column once without copying its values.

        Args:
            frame: A normalized history layer with unique string column names.

        Returns:
            Columns whose order and scalar values follow the source layer.

        Raises:
            ValueError: If column names cannot identify individual source fields.
        """
        if not frame.columns.is_unique or not all(
            isinstance(name, str) for name in frame.columns
        ):
            message = "History columns require unique string names"
            raise ValueError(message)
        return cls(
            fields=types.MappingProxyType({
                name: tuple(frame[name]) for name in frame.columns
            }),
        )

    def select(self, positions: tuple[int, ...]) -> HistoryRows:
        """Share columns while retaining exactly the requested evidence order.

        Args:
            positions: Valid source positions, including repetitions when requested.

        Returns:
            A view that borrows the selected rows without copying their columns.
        """
        return HistoryRows(columns=self, positions=positions)


@dataclasses.dataclass(frozen=True, kw_only=True, slots=True)
class HistoryRow:
    """Read one position from shared columns without creating a pandas Series."""

    columns: HistoryColumns
    position: int

    def get(self, name: str, default: object = None) -> object:
        """Preserve absent fields separately from supplied missing scalar values.

        Args:
            name: Source field to read.
            default: Value returned only when the source field is absent.

        Returns:
            The original scalar at this position, or the supplied default.
        """
        values = self.columns.fields.get(name)
        return default if values is None else values[self.position]


@dataclasses.dataclass(frozen=True, kw_only=True, slots=True)
class HistoryRows:
    """Keep source columns shared across one fire's ordered evidence positions."""

    columns: HistoryColumns
    positions: tuple[int, ...]

    @property
    def empty(self) -> bool:
        """Match a frame's empty-axis rule for independent-history fallback.

        Returns:
            Whether the selection has no rows or no columns.
        """
        return not self.positions or not self.columns.fields

    def get(self, name: str, default: tuple[object, ...] = ()) -> tuple[object, ...]:
        """Read selected column values for sparse-history fallback measurements.

        Args:
            name: Source field to read.
            default: Values returned only when the source field is absent.

        Returns:
            Selected scalars in evidence order, or the supplied default.
        """
        values = self.columns.fields.get(name)
        return (
            default
            if values is None
            else tuple(values[position] for position in self.positions)
        )


def prepare_source(frame: pd.DataFrame) -> Source:
    """Share normalized columns while retaining pandas access for unusual schemas.

    Args:
        frame: Source history whose cache and policy behavior must remain available.

    Returns:
        Shared columns, or the source frame when field names prevent materialization.
    """
    try:
        return HistoryColumns.from_frame(frame)
    except ValueError:
        return frame


def select_rows(source: Source, positions: tuple[int, ...]) -> Frame:
    """Select ordered evidence through the representation supported by its schema.

    Args:
        source: Shared columns or an unmodified source frame.
        positions: Valid source positions in the requested evidence order.

    Returns:
        A position view or pandas slice with exactly the requested rows.
    """
    if isinstance(source, HistoryColumns):
        return source.select(positions)
    return source.iloc[list(positions)]


def rows(frame: Frame, *, reverse: bool = False) -> typing.Iterator[Row]:
    """Read evidence in its selected order through either supported representation.

    Args:
        frame: Source frame or position view of shared columns.
        reverse: Whether to visit the selected evidence in reverse order.

    Yields:
        Rows with their original field values.
    """
    if isinstance(frame, HistoryRows):
        positions = reversed(frame.positions) if reverse else iter(frame.positions)
        for position in positions:
            yield HistoryRow(columns=frame.columns, position=position)
    else:
        source = frame.iloc[::-1] if reverse else frame
        for _, row in source.iterrows():
            yield row


def last_row(frame: Frame) -> Row:
    """Read the final selected observation for undated current-area fallbacks.

    Args:
        frame: A nonempty source frame or position view.

    Returns:
        The last selected row, preserving source order.
    """
    if isinstance(frame, HistoryRows):
        return HistoryRow(columns=frame.columns, position=frame.positions[-1])
    return frame.iloc[-1]


def has_field(row: Row, name: str) -> bool:
    """Identify normalized reporting rows independently of their scalar values.

    Args:
        row: One source row.
        name: Source field whose presence controls parsing.

    Returns:
        Whether the row's source contains the named field.
    """
    if isinstance(row, HistoryRow):
        return name in row.columns.fields
    return name in row.index
