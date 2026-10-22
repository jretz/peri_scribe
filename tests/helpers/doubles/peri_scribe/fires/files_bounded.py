"""Keep bounded publication tests independent of external boundary inventories."""

from __future__ import annotations

import pathlib
import typing

import peri_scribe.fires.bounded_sources
import peri_scribe.fires.index
import peri_scribe.models
import peri_scribe.perimeters.border_classification
import tests.helpers.doubles.errors
import tests.helpers.factories.peri_scribe.geo.catalog


if typing.TYPE_CHECKING:
    import pytest


def configure(
    monkeypatch: pytest.MonkeyPatch,
    year: pathlib.Path,
    *,
    classified: bool = False,
) -> None:
    """Supply a real authenticated catalog and controlled classification availability.

    Args:
        monkeypatch: The test's isolated dependency substitutions.
        year: Temporary publication year.
        classified: Whether a complete cached classification is available for each fire.
    """
    tests.helpers.factories.peri_scribe.geo.catalog.create(year / "sources")
    monkeypatch.setattr(
        peri_scribe.fires.bounded_sources,
        "load_boundaries",
        lambda _year: None,
    )
    monkeypatch.setattr(
        peri_scribe.perimeters.border_classification,
        "load_boundaries",
        tests.helpers.doubles.errors.raising_stub(OSError("boundaries unavailable")),
    )
    if classified:
        monkeypatch.setattr(
            peri_scribe.fires.index,
            "cached_classification",
            classification,
        )


def classification(key: str) -> peri_scribe.models.FireClassification:
    """Supply a valid cached scalar result without changing its owning publication.

    Args:
        key: The requested fire identity.

    Returns:
        Complete classification facts used by the tiny fixture's source rows.
    """
    return peri_scribe.models.FireClassification(
        classification=peri_scribe.models.BorderClassification.INSIDE_CALIFORNIA,
        inside_area_fraction=1.0,
        outside_area_fraction=0.0,
    )
