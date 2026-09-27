import pathlib

import pytest

import peri_scribe.fires.components
import tests.helpers.factories.peri_scribe.component_identity


@pytest.mark.parametrize("serials", [(9, 10), (999999, 1000000)])
def test_component_id_retains_numeric_earlier_anchor_when_snapshot_appended(
    tmp_path: pathlib.Path,
    serials: tuple[int, int],
) -> None:
    read = tests.helpers.factories.peri_scribe.component_identity.sources(tmp_path)
    paths = tuple(
        read.paths[0].with_name(f"{serial},lastEdit=0.gpkg") for serial in serials
    )
    rows = (read.rows[0], read.rows[0])
    anchors = peri_scribe.fires.components.anchors(rows, paths)
    assert peri_scribe.fires.components.component_id(anchors) == (
        peri_scribe.fires.components.component_id(anchors[:1])
    )
