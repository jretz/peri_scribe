"""Cache identity includes every dependency and output publication is recoverable."""

import pathlib
import tempfile

import hypothesis

import peri_scribe.fires.reuse
import peri_scribe.models
import tests.helpers.strategies.peri_scribe.fires.reuse


# This test is slow, so limit examples to keep routine test runs fast.
@hypothesis.settings(max_examples=25)
@hypothesis.given(
    layers=tests.helpers.strategies.peri_scribe.fires.reuse.history_layers(),
)
def test_read_rows_preserves_layer_and_fire_partitions(
    layers: list[peri_scribe.models.LayerData],
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
