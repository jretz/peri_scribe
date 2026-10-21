"""Slim source projections preserve exact anchor choices and complete row evidence."""

import itertools
import pathlib
import tempfile

import hypothesis

import peri_scribe.fires.components
import peri_scribe.geo.fingerprints
import peri_scribe.geo.package
import peri_scribe.geo.source_summaries
import spatial_data.product_cache
import tests.helpers.strategies.peri_scribe.geo.database


@hypothesis.settings(max_examples=40, deadline=None)
@hypothesis.given(
    contents=tests.helpers.strategies.peri_scribe.geo.database.snapshot_contents(),
)
def test_summarize_preserves_every_subset_anchor_choice_and_codec(
    contents: peri_scribe.geo.package.GeopackageContents,
) -> None:
    path = pathlib.Path("feed/000___/000001,lastEdit=1.gpkg")
    summary = peri_scribe.geo.source_summaries.summarize(path, contents)
    anchors = peri_scribe.fires.components.anchors(
        contents.rows,
        (path,) * len(contents.rows),
    )
    for count in range(1, len(contents.rows) + 1):
        for indices in itertools.combinations(range(len(contents.rows)), count):
            selected = min(indices, key=lambda index: summary.rows[index].anchor_order)
            assert summary.rows[selected].anchor_digest == (
                peri_scribe.fires.components.component_id(
                    anchors[index] for index in indices
                )
            )
    assert [row.row_key for row in summary.rows] == [
        peri_scribe.geo.fingerprints.complete_row_fingerprint(row)
        for row in contents.rows
    ]
    with (
        tempfile.TemporaryDirectory() as directory,
        spatial_data.product_cache.scope(pathlib.Path(directory) / "cache", "context"),
    ):
        peri_scribe.geo.source_summaries.store_summary(
            path,
            pathlib.Path(),
            "1" * 64,
            summary,
        )
        assert (
            peri_scribe.geo.source_summaries.read_snapshot_summary(
                path,
                pathlib.Path(),
                "1" * 64,
            )
            == summary
        )
