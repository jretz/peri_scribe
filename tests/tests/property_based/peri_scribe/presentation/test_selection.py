"""Area qualification uses the same evidence and history as the displayed estimate."""

from __future__ import annotations

import typing

import hypothesis

import peri_scribe.presentation.selection
import tests.helpers.strategies.peri_scribe.presentation.selection


if typing.TYPE_CHECKING:
    import geopandas


@hypothesis.given(
    scenario=tests.helpers.strategies.peri_scribe.presentation.selection.aliased_histories(),
)
def test_area_groups_preserves_the_canonical_identity_partition(
    scenario: tuple[
        geopandas.GeoDataFrame,
        dict[str, str],
        dict[tuple[str, str], list[int]],
    ],
) -> None:
    frame, aliases, expected = scenario
    groups = peri_scribe.presentation.selection.area_groups(frame, aliases)
    assert {key: group["row_id"].tolist() for key, group in groups.items()} == expected
