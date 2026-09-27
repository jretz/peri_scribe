"""Correction scenarios retain observation dates independently of publication dates."""

import dataclasses
import datetime
import typing

import tests.helpers.factories.peri_scribe.fire_updates
from measurement_units import units


if typing.TYPE_CHECKING:
    import peri_scribe.presentation.fire_data


EPOCH = datetime.datetime(2026, 9, 26, tzinfo=datetime.UTC)


def fire(
    identifiers: frozenset[str],
    observation: int | None,
    *,
    name: str = "Timber",
) -> peri_scribe.presentation.fire_data.FireSummary:
    """Give a correction its own mapping evidence and visible acreage.

    Args:
        identifiers: The identifiers currently attributed to the fire.
        observation: Hours after the shared epoch, or an undated observation.
        name: The current display name, independent of the history's identity.

    Returns:
        An interesting mapped fire with dated or undated survey evidence.
    """
    original = tests.helpers.factories.peri_scribe.fire_updates.mapped_fire()
    return dataclasses.replace(
        original,
        name=name,
        identifiers=identifiers,
        perimeters=(
            dataclasses.replace(
                original.perimeters[0],
                observation_time=(
                    None
                    if observation is None
                    else EPOCH + datetime.timedelta(hours=observation)
                ),
                area=(100 if observation is None else 100 + abs(observation))
                * units.acres,
                source_references=frozenset({f"survey-{observation}"}),
            ),
        ),
    )
