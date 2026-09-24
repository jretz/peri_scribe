"""Observe deterministic preparation while leaving its output unchanged."""

from __future__ import annotations

import typing

import peri_scribe.areas


if typing.TYPE_CHECKING:
    import pandas as pd
    import pytest


def record_preparations(monkeypatch: pytest.MonkeyPatch) -> list[frozenset[str]]:
    """Record only the identities whose expensive evidence preparation runs.

    Args:
        monkeypatch: Replaces the preparation boundary for the current test.

    Returns:
        A list populated with each prepared history's source identities.
    """
    original = peri_scribe.areas.prepare_history
    calls: list[frozenset[str]] = []

    def prepare(
        perimeters: pd.DataFrame,
        points: pd.DataFrame,
        incidents: pd.DataFrame | None = None,
    ) -> peri_scribe.areas.PreparedHistory:
        """Keep the ordinary calculation while exposing invalidation decisions.

        Args:
            perimeters: Selected perimeter evidence.
            points: Selected point evidence.
            incidents: Optional selected reporting evidence.

        Returns:
            The ordinary prepared history.
        """
        calls.append(
            frozenset(
                str(identifier)
                for frame in (perimeters, points, incidents)
                if frame is not None
                for identifier in frame.get("fire_identifier", ())
            ),
        )
        return original(perimeters, points, incidents)

    monkeypatch.setattr(peri_scribe.areas, "prepare_history", prepare)
    return calls


def reject_serialization(_value: object) -> bytes:
    """Simulate a deterministic result containing an unsupported scalar type.

    Args:
        _value: Completed preparation whose serialization is intentionally unavailable.

    Raises:
        ValueError: Because the prepared result cannot use the persistent cache.
    """
    message = "Unsupported cache value"
    raise ValueError(message)
