"""Build inputs for models tests."""

from __future__ import annotations

import datetime
import typing

import peri_scribe.models


if typing.TYPE_CHECKING:
    import shapely


ACTIVE = peri_scribe.models.FireStatus.ACTIVE


INACTIVE = peri_scribe.models.FireStatus.INACTIVE


def fire_record(
    name: str,
    status: peri_scribe.models.FireStatus,
    identifiers: typing.Iterable[str] = (),
    *,
    names: typing.Iterable[str] | None = None,
    geometry: shapely.Geometry | None = None,
    observed_at: datetime.datetime | None = None,
) -> peri_scribe.models.FireRecord:
    """Build a fire record for a test.

    Args:
        name: The record's display name.
        status: The record's status.
        identifiers: The record's normalized identifiers.
        names: The record's normalized name keys; defaults to the display name's
            normalization.
        geometry: The record's geometry.
        observed_at: The record's observation time.

    Returns:
        The record.
    """
    name_keys = (
        frozenset(names)
        if names is not None
        else frozenset({peri_scribe.models.normalize_fire_name(name)})
    )
    return peri_scribe.models.FireRecord(
        name=name,
        status=status,
        identifiers=frozenset(identifiers),
        names=name_keys,
        geometry=geometry,
        observed_at=observed_at,
    )


def fire(
    name: str = "Bug",
    identifier: str | None = "2026-nvccd-030683",
) -> peri_scribe.models.Fire:
    """Build a fire for a test.

    Args:
        name: The fire's name.
        identifier: The fire's canonical identifier.

    Returns:
        The fire.
    """
    return peri_scribe.models.Fire(
        name=name,
        status=ACTIVE,
        identifier=identifier,
        aliases=frozenset({identifier}) if identifier is not None else frozenset(),
    )
