"""Cache identity includes every dependency and output publication is recoverable."""

from __future__ import annotations

import pathlib
import tempfile
import typing

import hypothesis

import peri_scribe.fires.reuse
import tests.helpers.strategies.peri_scribe.fires.reuse


# File I/O has host-dependent latency; bound examples rather than elapsed time.
if typing.TYPE_CHECKING:
    import spatial_data.layers


@hypothesis.settings(max_examples=25, deadline=None)
@hypothesis.given(
    layers=tests.helpers.strategies.peri_scribe.fires.reuse.history_layers(),
)
def test_read_rows_preserves_layer_and_fire_partitions(
    layers: list[spatial_data.layers.LayerData],
) -> None:
    with tempfile.TemporaryDirectory() as directory:
        path = pathlib.Path(directory) / "history.gpkg"
        peri_scribe.fires.reuse.write_layers(path, layers)
        cached = peri_scribe.fires.reuse.read_rows(
            path,
            tuple(layer.name for layer in layers),
        )
    assert set(cached) == {layer.name for layer in layers}
    for layer in layers:
        records = layer.dataframe.to_dict("records")
        keys = {row["derivation_key"] for row in records}
        assert cached[layer.name] == {
            key: [row for row in records if row["derivation_key"] == key]
            for key in keys
        }
