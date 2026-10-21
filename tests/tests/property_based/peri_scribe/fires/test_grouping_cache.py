"""Compare changed-history dependency reuse with exhaustive current grouping."""

from __future__ import annotations

import pathlib
import tempfile

import hypothesis
import hypothesis.strategies

import peri_scribe.fires.grouping
import peri_scribe.models
import spatial_data.product_cache
import tests.helpers.factories.peri_scribe.fires.grouping_cache
import tests.helpers.reference.peri_scribe.fires.grouping
import tests.helpers.strategies.peri_scribe.fires.grouping


@hypothesis.given(
    histories=hypothesis.strategies.lists(
        tests.helpers.strategies.peri_scribe.fires.grouping.fire_records(),
        min_size=1,
        max_size=5,
    ),
)
@hypothesis.settings(max_examples=40)
def test_group_fire_record_indices_reuses_only_exact_current_dependencies(
    histories: list[list[peri_scribe.models.FireRecord]],
) -> None:
    with tempfile.TemporaryDirectory() as directory:
        for records in histories:
            with spatial_data.product_cache.scope(
                pathlib.Path(directory) / "products.sqlite",
                "property context",
            ):
                actual = peri_scribe.fires.grouping.group_fire_record_indices(
                    records,
                    row_keys=tests.helpers.factories.peri_scribe.fires.grouping_cache.row_keys(
                        records,
                    ),
                )
            assert (
                actual
                == tests.helpers.reference.peri_scribe.fires.grouping.reference_groups(
                    records,
                )
            )
