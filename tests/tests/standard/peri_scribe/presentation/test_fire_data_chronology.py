"""Canonical aliases retain one chronological sequence of drawable observations."""

import datetime

import peri_scribe.presentation.fire_data
import tests.helpers.factories.geometry
import tests.helpers.factories.peri_scribe.kml.parsing


def test_fire_perimeters_merges_interleaved_alias_histories_chronologically() -> None:
    geometry = tests.helpers.factories.geometry.square(1.0)
    undated = tests.helpers.factories.peri_scribe.kml.parsing.perimeter_with_time(
        geometry,
    )
    earlier = tests.helpers.factories.peri_scribe.kml.parsing.perimeter_with_time(
        geometry,
        datetime.datetime(2026, 1, 1, tzinfo=datetime.UTC),
    )
    later = tests.helpers.factories.peri_scribe.kml.parsing.perimeter_with_time(
        geometry,
        datetime.datetime(2026, 1, 2, tzinfo=datetime.UTC),
    )
    assert peri_scribe.presentation.fire_data.fire_perimeters(
        frozenset({"alias-a", "alias-b"}),
        "Shared fire",
        {"alias-a": [later], "alias-b": [undated, earlier]},
        {},
    ) == (undated, earlier, later)
