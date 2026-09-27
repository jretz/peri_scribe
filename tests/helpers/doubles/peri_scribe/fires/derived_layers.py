"""Attempt competing publication at each protected geography layer boundary."""

from __future__ import annotations

import dataclasses
import pathlib
import typing

import peri_scribe.fires.derived_layers
import peri_scribe.fires.differential
import peri_scribe.fires.files
import peri_scribe.pipeline_state


if typing.TYPE_CHECKING:
    import geopandas
    import pytest


@dataclasses.dataclass(kw_only=True)
class LockedReader:
    """Confirm every layer is read while another writer remains excluded."""

    directory: pathlib.Path
    original: typing.Callable[[pathlib.Path, str], geopandas.GeoDataFrame]
    calls: int = 0

    def read(self, path: pathlib.Path, layer: str) -> geopandas.GeoDataFrame:
        """Check exclusion at an actual file-read boundary.

        Args:
            path: The file supplying this layer.
            layer: The layer whose contents must stay in the captured generation.

        Returns:
            The real normalized GeoPackage contents.
        """
        with peri_scribe.pipeline_state.run_lock(self.directory) as acquired:
            assert not acquired
        self.calls += 1
        return self.original(path, layer)


def stub_reader(
    monkeypatch: pytest.MonkeyPatch,
    read_layer: typing.Callable[[pathlib.Path, str], geopandas.GeoDataFrame],
) -> None:
    """Supply already authenticated inputs to tests of downstream presentation.

    Args:
        monkeypatch: Restore the derived reader after the test.
        read_layer: Existing synthetic layer callback used by the presentation scenario.
    """

    def read(
        year: pathlib.Path,
        *,
        tolerate_missing: bool,
    ) -> peri_scribe.fires.derived_layers.DerivedLayers:
        """Keep presentation tests independent of the separately tested file protocol.

        Args:
            year: The requested year used to select synthetic layers.
            tolerate_missing: Reader policy, irrelevant for supplied complete inputs.

        Returns:
            The complete synthetic geography input.
        """
        full = peri_scribe.fires.files.history_geopackage_path(year)
        differential = peri_scribe.fires.differential.differential_geopackage_path(year)
        return peri_scribe.fires.derived_layers.DerivedLayers(
            perimeters=read_layer(full, peri_scribe.fires.files.PERIMETER_LAYER_NAME),
            points=read_layer(full, peri_scribe.fires.files.POINT_LAYER_NAME),
            differential_perimeters=read_layer(
                differential,
                peri_scribe.fires.files.PERIMETER_LAYER_NAME,
            ),
        )

    monkeypatch.setattr(peri_scribe.fires.derived_layers, "read_derived_layers", read)
