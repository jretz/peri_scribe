"""Area qualification uses the same evidence and history as the displayed estimate."""

from __future__ import annotations

import re
import typing

import hypothesis

import peri_scribe.kml.selection
import tests.helpers.strategies.peri_scribe.kml.selection


if typing.TYPE_CHECKING:
    import geopandas


@hypothesis.given(
    scenario=tests.helpers.strategies.peri_scribe.kml.selection.aliased_histories(),
)
def test_area_groups_preserves_the_canonical_identity_partition(
    scenario: tuple[
        geopandas.GeoDataFrame,
        dict[str, str],
        dict[tuple[str, str], list[int]],
    ],
) -> None:
    frame, aliases, expected = scenario
    groups = peri_scribe.kml.selection.area_groups(frame, aliases)
    assert {key: group["row_id"].tolist() for key, group in groups.items()} == expected


@hypothesis.given(
    requests=tests.helpers.strategies.peri_scribe.kml.selection.filename_requests(),
)
def test_unique_filename_prefix_allocates_distinct_safe_names(
    requests: list[tuple[str | None, str]],
) -> None:
    used: set[str] = set()
    for identifier, name in requests:
        prefix = peri_scribe.kml.selection.unique_filename_prefix(
            identifier,
            name,
            frozenset(used),
        )
        assert prefix not in used
        assert re.fullmatch(r"[a-z0-9]+(?:-[a-z0-9]+)*", prefix)
        used.add(prefix)
