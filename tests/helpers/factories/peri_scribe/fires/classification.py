"""Build inputs for classification tests."""

from __future__ import annotations

import pathlib

import shapely.geometry

import peri_scribe.fires.sources
import peri_scribe.models
import tests.helpers.factories.peri_scribe.models


def record_groups(
    *,
    fire: peri_scribe.models.Fire,
    complex_identifiers: frozenset[str] = frozenset(),
) -> peri_scribe.fires.sources.FireRecordGroups:
    """Group one fire observation for border classification tests.

    Args:
        fire: Fire whose observations are being grouped or derived.
        complex_identifiers: Identifiers marking complex-parent records in the group.

    Returns:
        A single-fire group with the requested complex membership identifiers.
    """
    identifiers = frozenset({fire.identifier}) if fire.identifier else frozenset()
    record = tests.helpers.factories.peri_scribe.models.fire_record(
        "Park Fire",
        tests.helpers.factories.peri_scribe.models.ACTIVE,
        identifiers=identifiers,
        geometry=shapely.geometry.Point(-120.0, 39.0),
    )
    path = pathlib.Path(
        "sources/CA_Perimeters_NIFC_FIRIS_public_view_0/000___/000000,lastEdit=0.gpkg",
    )
    return peri_scribe.fires.sources.FireRecordGroups(
        records=(record,),
        record_paths=(path,),
        fires=(fire,),
        groups=((0,),),
        complex_identifiers=complex_identifiers,
    )
