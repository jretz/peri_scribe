"""Isolate map-input adapters from independently checked generation and area policy."""

from __future__ import annotations

import typing

import peri_scribe.fires.derived_layers
import peri_scribe.fires.differential
import peri_scribe.fires.files
import peri_scribe.presentation.index


if typing.TYPE_CHECKING:
    import pytest

    import tests.helpers.factories.peri_scribe.kml.prepared_inputs


def legacy_paths(
    monkeypatch: pytest.MonkeyPatch,
    geography: tests.helpers.factories.peri_scribe.kml.prepared_inputs.Geography,
) -> None:
    """Select the retained GeoPackage adapter for these isolated compatibility tests.

    Args:
        monkeypatch: The current test's replacement scope.
        geography: Explicit GeoPackage paths created by the independent fixture.
    """
    monkeypatch.setattr(
        peri_scribe.fires.files,
        "HISTORY_OUTPUT_FILENAME",
        geography.full_path.name,
    )
    monkeypatch.setattr(
        peri_scribe.fires.differential,
        "DIFFERENTIAL_OUTPUT_FILENAME",
        geography.differential_path.name,
    )


def fixed_preparation(
    monkeypatch: pytest.MonkeyPatch,
    geography: tests.helpers.factories.peri_scribe.kml.prepared_inputs.Geography,
) -> None:
    """Retain actual file readers while fixing upstream policy and authentication.

    Args:
        monkeypatch: The current test's replacement scope.
        geography: Real test files and independently supplied complete histories.
    """
    legacy_paths(monkeypatch, geography)
    monkeypatch.setattr(
        peri_scribe.fires.derived_layers,
        "authenticated_pair",
        lambda *_args, **_kwargs: geography.identity,
    )
    monkeypatch.setattr(
        peri_scribe.presentation.index,
        "prepare_histories",
        lambda *_args, **_kwargs: geography.histories,
    )
