"""Standalone borrowed views need their current source schema identities."""

import geopandas
import pytest

import peri_scribe.history_columns
import peri_scribe.presentation.text


def test_latest_fingerprints_declines_views_without_schema_identity() -> None:
    columns = peri_scribe.history_columns.HistoryColumns.from_frame(
        geopandas.GeoDataFrame(),
    )
    with pytest.raises(ValueError, match="schema fingerprints"):
        peri_scribe.presentation.text.latest_fingerprints((columns.select(()),))
