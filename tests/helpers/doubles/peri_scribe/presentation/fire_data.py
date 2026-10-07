"""Observe materialization without replacing history selection or preparation."""

from __future__ import annotations

import typing

import peri_scribe.presentation.history_index


if typing.TYPE_CHECKING:
    import geopandas
    import pytest


def record_selections(
    monkeypatch: pytest.MonkeyPatch,
) -> list[tuple[int, tuple[int, ...]]]:
    """Keep source-frame identity and row membership beside real selected data.

    Args:
        monkeypatch: The current test's dependency replacement scope.

    Returns:
        The selected frame identities and their requested row positions.
    """
    original = peri_scribe.presentation.history_index.select_rows
    calls: list[tuple[int, tuple[int, ...]]] = []

    def select_rows(
        frame: geopandas.GeoDataFrame,
        positions: tuple[int, ...],
    ) -> geopandas.GeoDataFrame:
        """Retain real row selection while exposing unnecessary materialization.

        Args:
            frame: The source history frame.
            positions: Selected row positions within that frame.

        Returns:
            The original selector's matching rows.
        """
        calls.append((id(frame), positions))
        return original(frame, positions)

    monkeypatch.setattr(
        peri_scribe.presentation.history_index,
        "select_rows",
        select_rows,
    )
    return calls
