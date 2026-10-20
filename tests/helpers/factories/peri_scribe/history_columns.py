"""Exercise the same source evidence through each supported history representation."""

from __future__ import annotations

import typing

import peri_scribe.history_columns


if typing.TYPE_CHECKING:
    import pandas as pd


def representation(
    frame: pd.DataFrame,
    *,
    columnar: bool,
) -> peri_scribe.history_columns.Frame:
    """Preserve the entire input order while choosing its access representation.

    Args:
        frame: Source evidence to expose to the unchanged policy.
        columnar: Whether to borrow scalars from shared columns.

    Returns:
        The original frame or a complete positional view.
    """
    if columnar:
        return peri_scribe.history_columns.HistoryColumns.from_frame(frame).select(
            tuple(range(len(frame))),
        )
    return frame
