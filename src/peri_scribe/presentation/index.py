"""Prepare histories and select the fires shared by output formats."""

from __future__ import annotations

import dataclasses
import typing

import peri_scribe.areas
import peri_scribe.execution
import peri_scribe.logging
import peri_scribe.models
import peri_scribe.phases
import peri_scribe.presentation.selection


if typing.TYPE_CHECKING:
    import geopandas


@dataclasses.dataclass(frozen=True, kw_only=True)
class SharedHistories:
    """Retain source frames for the lifetime of their prepared histories."""

    sources: tuple[object, ...]
    histories: dict[
        peri_scribe.presentation.selection.AreaKey,
        peri_scribe.areas.PreparedHistory,
    ]


def prepare_histories(
    index: peri_scribe.models.FireIndex,
    perimeters: geopandas.GeoDataFrame,
    points: geopandas.GeoDataFrame,
    incident_rows: geopandas.GeoDataFrame | None = None,
) -> dict[
    peri_scribe.presentation.selection.AreaKey,
    peri_scribe.areas.PreparedHistory,
]:
    """Let filtering and presentation share each fire's complete reporting evidence.

    Args:
        index: Fire identities and aliases used to combine history rows.
        perimeters: The full perimeter history layer.
        points: The point history layer.
        incident_rows: The optional independent incident history.

    Returns:
        Prepared reporting and area decisions keyed by canonical identity.
    """
    sources = (perimeters, points, incident_rows)
    key = (
        ("presentation_histories", index.model_dump_json(), tuple(map(id, sources)))
        if peri_scribe.execution.active()
        else None
    )
    shared = peri_scribe.execution.get(peri_scribe.execution.Group.HISTORIES, key)
    if isinstance(shared, SharedHistories) and all(
        previous is current
        for previous, current in zip(shared.sources, sources, strict=True)
    ):
        return shared.histories
    with peri_scribe.logging.log_phase(peri_scribe.phases.Phase.PREPARE_FIRE_HISTORIES):
        histories = peri_scribe.presentation.selection.prepare_histories(
            perimeters,
            points,
            incident_rows,
            aliases={
                identifier: entry.identifier or identifier
                for entry in index.fires
                for identifier in peri_scribe.presentation.selection.identifiers(entry)
            },
        )
    peri_scribe.execution.put(
        peri_scribe.execution.Group.HISTORIES,
        key,
        SharedHistories(sources=sources, histories=histories),
    )
    return histories


def area_qualified_index(
    index: peri_scribe.models.FireIndex,
    perimeters: geopandas.GeoDataFrame,
    points: geopandas.GeoDataFrame,
    incident_rows: geopandas.GeoDataFrame | None = None,
    *,
    histories: typing.Mapping[
        peri_scribe.presentation.selection.AreaKey,
        peri_scribe.areas.PreparedHistory,
    ]
    | None = None,
) -> peri_scribe.models.FireIndex:
    """Return *index* with every fire lacking a qualifying area indication removed.

    A fire stays when the shared area policy selects an estimate at least the minimum
    anywhere in its history. Later corrections cannot erase that qualification.

    Args:
        index: The fire index to filter.
        perimeters: The perimeter history layer.
        points: The point history layer.
        incident_rows: The optional independent incident history.
        histories: Already prepared histories keyed by fire identity, when available.

    Returns:
        The index holding only the qualifying fires.
    """
    if histories is None:
        histories = prepare_histories(index, perimeters, points, incident_rows)
    qualifying_keys = peri_scribe.presentation.selection.fires_with_qualifying_area(
        perimeters,
        points,
        peri_scribe.presentation.selection.MINIMUM_FIRE_AREA,
        incident_rows,
        histories=histories,
    )
    return peri_scribe.models.FireIndex(
        version=index.version,
        fires=[
            entry
            for entry in index.fires
            if peri_scribe.presentation.selection.fire_qualifies(
                peri_scribe.presentation.selection.identifiers(entry),
                entry.name,
                qualifying_keys,
            )
        ],
    )
