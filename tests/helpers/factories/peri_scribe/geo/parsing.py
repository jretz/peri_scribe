"""Build inputs for parsing tests."""

from __future__ import annotations

import pandas as pd


ITEM_VALUE = 7


def mission_row(mission: str, incident_name: str | None = None) -> pd.Series:
    """Represent a CA perimeter whose mission is available before incident assignment.

    Args:
        mission: The source's mission text, also used to distinguish test records.
        incident_name: The optional agency-provided incident name.

    Returns:
        Attributes in the configured CA feed's schema.
    """
    return pd.Series({
        "incident_name": incident_name,
        "displayStatus": "Active",
        "incident_number": None,
        "GlobalID": mission,
        "mission": mission,
        "poly_DateCurrent": "2026-09-23T20:41:37Z",
    })
