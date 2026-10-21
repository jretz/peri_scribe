"""Isolate map-input adapters from independently checked generation and area policy."""

from __future__ import annotations

import typing

import peri_scribe.fires.derived_layers
import peri_scribe.presentation.index


if typing.TYPE_CHECKING:
    import pytest

    import tests.helpers.factories.peri_scribe.kml.prepared_inputs


def fixed_preparation(
    monkeypatch: pytest.MonkeyPatch,
    geography: tests.helpers.factories.peri_scribe.kml.prepared_inputs.Geography,
) -> None:
    """Retain actual file readers while fixing upstream policy and authentication.

    Args:
        monkeypatch: The current test's replacement scope.
        geography: Real test files and independently supplied complete histories.
    """
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
