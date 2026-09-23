"""Publication scenarios preserve the identities selected by source grouping."""

import dataclasses
import datetime
import pathlib

import shapely
import time_machine

import peri_scribe.fire_updates
import peri_scribe.fires.grouping
import peri_scribe.models
import peri_scribe.presentation.fire_data
import tests.helpers.factories.peri_scribe.fire_updates
import tests.helpers.factories.peri_scribe.models
from measurement_units import units


def grouped_fires(
    fires: list[peri_scribe.presentation.fire_data.FireSummary],
) -> list[peri_scribe.presentation.fire_data.FireSummary]:
    """Apply upstream identity selection to summaries ordered by observation.

    Args:
        fires: Summaries whose last observation supplies each group's mapping history.

    Returns:
        Source-grouped summaries in case-insensitive display-name order.
    """
    records = [
        tests.helpers.factories.peri_scribe.models.fire_record(
            fire.name,
            fire.status,
            identifiers=fire.identifiers,
            geometry=fire.perimeters[-1].geometry,
            observed_at=fire.perimeters[-1].observation_time,
        )
        for fire in fires
    ]
    grouped = []
    for indices in peri_scribe.fires.grouping.group_fire_record_indices(records):
        identity = peri_scribe.fires.grouping.most_common_fire([
            records[index] for index in indices
        ])
        grouped.append(
            dataclasses.replace(
                fires[indices[-1]],
                name=identity.name,
                identifiers=identity.aliases,
            ),
        )
    return sorted(grouped, key=peri_scribe.presentation.fire_data.fire_name_key)


def publish_updates(
    year_directory: pathlib.Path,
    fires: list[peri_scribe.presentation.fire_data.FireSummary],
    now: datetime.datetime,
) -> peri_scribe.fire_updates.PreparedUpdates:
    """Acknowledge a successful publication without depending on the wall clock.

    Args:
        year_directory: Isolated publication directory.
        fires: The complete set of current summaries.
        now: This publication's completion time.

    Returns:
        The records and checkpoint acknowledged by the publication.
    """
    scores = peri_scribe.models.FireScores(version="test", fires=[])
    with time_machine.travel(now, tick=False):
        prepared = peri_scribe.fire_updates.prepare_updates(
            year_directory,
            fires,
            scores,
        )
        peri_scribe.fire_updates.write_updates(year_directory, prepared)
    return prepared


def publish_renamed(
    year_directory: pathlib.Path,
    now: datetime.datetime,
) -> peri_scribe.presentation.fire_data.FireSummary:
    """Reserve the original name history for its enriched and renamed owner.

    Args:
        year_directory: Isolated publication directory.
        now: The original name-only publication's completion time.

    Returns:
        The identified fire after its display name changes.
    """
    fire = tests.helpers.factories.peri_scribe.fire_updates.mapped_fire()
    original = dataclasses.replace(fire, identifiers=frozenset())
    renamed = dataclasses.replace(fire, name="Timber Complex")
    for offset, current in enumerate((original, fire, renamed)):
        publish_updates(
            year_directory,
            [current],
            now + datetime.timedelta(minutes=offset),
        )
    return renamed


def distant_namesake(
    now: datetime.datetime,
) -> peri_scribe.presentation.fire_data.FireSummary:
    """Keep a new name-only fire geographically distinct from its earlier namesake.

    Args:
        now: The new fire's mapping observation time.

    Returns:
        A 100-acre Timber perimeter distant from the standard Timber fixture.
    """
    fire = tests.helpers.factories.peri_scribe.fire_updates.mapped_fire()
    return dataclasses.replace(
        fire,
        identifiers=frozenset(),
        perimeters=(
            dataclasses.replace(
                fire.perimeters[-1],
                geometry=shapely.box(-110, 40, -109.9, 40.1),
                observation_time=now,
                area=100 * units.acres,
            ),
        ),
    )
