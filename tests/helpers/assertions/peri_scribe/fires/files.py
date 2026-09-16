"""Compare files behavior through reusable assertions."""

from __future__ import annotations

import typing

import geopandas.testing


if typing.TYPE_CHECKING:
    import peri_scribe.fires.derived_layers


def assert_histories_equal(
    left: peri_scribe.fires.derived_layers.DerivedLayers,
    right: peri_scribe.fires.derived_layers.DerivedLayers,
) -> None:
    """Require reused and rebuilt histories to retain the same evidence and geometry.

    Args:
        left: The histories produced by an incremental rebuild.
        right: The independently rebuilt reference histories.
    """
    for name in ("perimeters", "points", "differential_perimeters", "incidents"):
        first = getattr(left, name)
        second = getattr(right, name)
        geopandas.testing.assert_geodataframe_equal(first, second)
        assert list(first.geometry.to_wkb()) == list(second.geometry.to_wkb())
