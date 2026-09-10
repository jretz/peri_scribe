"""Tests for peri_scribe.fires.derived_layers."""

from __future__ import annotations

import pathlib
import typing

import peri_scribe.fires.derived_layers
import peri_scribe.geo.reading
import tests.factories
import tests.peri_scribe.fires.fire_helpers


if typing.TYPE_CHECKING:
    import pytest


def test_read_layer_if_present_returns_empty_without_file(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(pathlib.Path, "is_file", lambda _self: False)
    result = peri_scribe.fires.derived_layers.read_layer_if_present(
        pathlib.Path("/missing.gpkg"),
        "layer",
    )
    assert result.empty


def test_read_layer_if_present_reads_existing_file(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    frame = tests.peri_scribe.fires.fire_helpers.perimeter_frame(
        [{"fire_name": "Bug"}],
        [tests.factories.square(1.0)],
    )
    monkeypatch.setattr(pathlib.Path, "is_file", lambda _self: True)
    monkeypatch.setattr(
        peri_scribe.geo.reading,
        "read_layer",
        lambda _path, _layer_name: frame,
    )
    result = peri_scribe.fires.derived_layers.read_layer_if_present(
        pathlib.Path("/present.gpkg"),
        "perimeter_history",
    )
    assert result is frame
