"""Prepare fire summaries and history evidence shared by output formats."""

from __future__ import annotations

import dataclasses
import typing

import peri_scribe.areas
import peri_scribe.fires.scoring
import peri_scribe.models
import peri_scribe.perimeters.progression
import peri_scribe.presentation.descriptions
import peri_scribe.presentation.history_index
import peri_scribe.presentation.perimeters
import peri_scribe.presentation.selection
import peri_scribe.presentation.text


if typing.TYPE_CHECKING:
    import geopandas
    import shapely


@dataclasses.dataclass(frozen=True, kw_only=True)
class FireSummary:
    """One fire's identity, latest facts, location, and perimeter history.

    These values give reports and maps the same basis for ranking and descriptions.
    ``type_one`` reflects the latest point-history designation used by scoring.
    """

    name: str
    status: peri_scribe.models.FireStatus
    point: shapely.Point | None
    perimeters: tuple[peri_scribe.presentation.perimeters.Perimeter, ...]
    progression_rings: tuple[peri_scribe.perimeters.progression.Ring, ...] = ()
    description: peri_scribe.presentation.descriptions.FireDescription | None = None
    identifiers: frozenset[str] = frozenset()
    type_one: bool = False


class NamedFire(typing.Protocol):
    """Anything the fire views order by name."""

    @property
    def name(self) -> str:
        """The fire's name.

        Returns:
            The display name of the fire.
        """
        ...


def fire_name_key(named: NamedFire) -> str:
    """Return the ordering key that sorts fires by name, ignoring case.

    Folding case keeps the order stable when two names differ only in case, so every
    view lists the same fires in the same order.

    Args:
        named: The fire to key.

    Returns:
        The fire's case-folded name.
    """
    return named.name.casefold()


def descending_value_name_key(ranked: tuple[FireSummary, float]) -> tuple[float, str]:
    """Return the ordering key that ranks fires by value, then by name.

    The largest value comes first, and fires whose values tie keep one stable order.

    Args:
        ranked: A fire and the value it is ranked by.

    Returns:
        The key: the negated value followed by the case-folded name.
    """
    fire, value = ranked
    return (-value, fire_name_key(fire))


MINIMUM_RING_AREA = peri_scribe.perimeters.progression.MINIMUM_RING_AREA


def progression_ring(
    perimeter: peri_scribe.presentation.perimeters.Perimeter,
) -> peri_scribe.perimeters.progression.Ring | None:
    """Return *perimeter* as a growth ring, or None when it is too small.

    The ring's area is measured geodesically from its geometry so the growth-window and
    color logic later work in true map area rather than whatever acreage the source
    reported.

    Args:
        perimeter: The differential perimeter to turn into a ring.

    Returns:
        The ring, or None when its area is at most one square meter.
    """
    area = perimeter.measured_area
    if area <= MINIMUM_RING_AREA:
        return None
    return peri_scribe.perimeters.progression.Ring(
        geometry=perimeter.geometry,
        observation_time=perimeter.observation_time,
        area=area,
        added_area=perimeter.added_area,
        sequence_digest=perimeter.sequence_digest,
    )


def fire_perimeters(
    fire_identifiers: frozenset[str],
    entry_name: str,
    perimeter_by_identifier: dict[
        str,
        list[peri_scribe.presentation.perimeters.Perimeter],
    ],
    perimeter_by_name: dict[str, list[peri_scribe.presentation.perimeters.Perimeter]],
) -> tuple[peri_scribe.presentation.perimeters.Perimeter, ...]:
    """Return one fire's perimeters in chronological order.

    Args:
        fire_identifiers: The fire's identifiers.
        entry_name: The fire's name.
        perimeter_by_identifier: Perimeters keyed by identifier.
        perimeter_by_name: Perimeters keyed by name.

    Returns:
        The fire's perimeters, oldest first.
    """
    perimeters: list[peri_scribe.presentation.perimeters.Perimeter] = []
    for identifier in sorted(fire_identifiers):
        perimeters.extend(perimeter_by_identifier.get(identifier, []))
    if not fire_identifiers:
        perimeters.extend(perimeter_by_name.get(entry_name, []))
    return tuple(perimeters)


@dataclasses.dataclass(frozen=True, kw_only=True)
class PendingFire:
    """Retain shared evidence while each fire's charts are rendered.

    Attributes:
        entry: The fire's indexed identity and status.
        identifiers: Its canonical identifier and aliases.
        perimeters: Full mapping observations for the output folders.
        progression_rings: Differential rings available for progression views.
        perimeter_positions: Row positions used to recover descriptive perimeter fields.
        point_positions: Row positions used to recover descriptive point fields.
        history: Prepared reports and area decisions, when presentation is needed.
    """

    entry: peri_scribe.models.FireIndexEntry
    identifiers: frozenset[str]
    perimeters: tuple[peri_scribe.presentation.perimeters.Perimeter, ...]
    progression_rings: tuple[peri_scribe.perimeters.progression.Ring, ...]
    perimeter_positions: tuple[int, ...]
    point_positions: tuple[int, ...]
    history: peri_scribe.areas.PreparedHistory | None = None


def prepare_fires(
    *,
    index: peri_scribe.models.FireIndex,
    perimeters: geopandas.GeoDataFrame,
    points: geopandas.GeoDataFrame,
    perimeter_by_identifier: dict[
        str,
        list[peri_scribe.presentation.perimeters.Perimeter],
    ],
    perimeter_by_name: dict[str, list[peri_scribe.presentation.perimeters.Perimeter]],
    ring_by_identifier: dict[str, list[peri_scribe.presentation.perimeters.Perimeter]],
    ring_by_name: dict[str, list[peri_scribe.presentation.perimeters.Perimeter]],
    incident_rows: geopandas.GeoDataFrame | None = None,
    histories: typing.Mapping[
        peri_scribe.presentation.selection.AreaKey,
        peri_scribe.areas.PreparedHistory,
    ]
    | None = None,
) -> list[PendingFire]:
    """Retain indexed history evidence for each fire's shared facts.

    Row positions avoid repeated scans and duplicated history-frame slices. Prepared
    histories keep area and reporting decisions consistent across output formats.

    Args:
        index: Fire identities and current status.
        perimeters: The perimeter history layer.
        points: The point history layer.
        perimeter_by_identifier: Perimeters keyed by identifier.
        perimeter_by_name: Perimeters keyed by name.
        ring_by_identifier: Differential perimeters keyed by identifier.
        ring_by_name: Differential perimeters keyed by name.
        incident_rows: The optional independent reporting history.
        histories: Already prepared histories keyed by canonical fire identity.

    Returns:
        Each fire's identity, geography, and reporting evidence in index order.
    """
    perimeter_index = peri_scribe.presentation.history_index.HistoryRowIndex.from_frame(
        perimeters,
    )
    point_index = peri_scribe.presentation.history_index.HistoryRowIndex.from_frame(
        points,
    )
    incident_index = optional_history_index(incident_rows)
    pending: list[PendingFire] = []
    for entry in index.fires:
        fire_identifiers = peri_scribe.presentation.selection.identifiers(entry)
        perimeter_observations = fire_perimeters(
            fire_identifiers,
            entry.name,
            perimeter_by_identifier,
            perimeter_by_name,
        )
        progression_rings = tuple(
            ring
            for observation in fire_perimeters(
                fire_identifiers,
                entry.name,
                ring_by_identifier,
                ring_by_name,
            )
            if (ring := progression_ring(observation)) is not None
        )
        perimeter_positions = perimeter_index.positions_for(
            fire_identifiers,
            entry.name,
        )
        point_positions = point_index.positions_for(fire_identifiers, entry.name)
        perimeter_rows = peri_scribe.presentation.history_index.select_rows(
            perimeters,
            perimeter_positions,
        )
        point_rows = peri_scribe.presentation.history_index.select_rows(
            points,
            point_positions,
        )
        history = (
            None
            if histories is None
            else histories.get(
                peri_scribe.presentation.selection.fire_area_key(
                    entry.identifier,
                    entry.name,
                ),
            )
        )
        if history is None:
            history = peri_scribe.areas.prepare_history(
                perimeter_rows,
                point_rows,
                selected_incidents(
                    incident_rows,
                    incident_index,
                    fire_identifiers,
                    entry.name,
                ),
            )
        pending.append(
            PendingFire(
                entry=entry,
                identifiers=fire_identifiers,
                perimeters=perimeter_observations,
                progression_rings=progression_rings,
                perimeter_positions=perimeter_positions,
                point_positions=point_positions,
                history=history,
            ),
        )
    return pending


@dataclasses.dataclass(frozen=True, kw_only=True)
class PreparedFire:
    """A fire's shared facts and evidence for consumers that draw history charts."""

    summary: FireSummary
    identifier: str | None
    history: peri_scribe.areas.PreparedHistory | None
    perimeter_positions: tuple[int, ...]
    point_positions: tuple[int, ...]


def prepare_fire_data(
    index: peri_scribe.models.FireIndex,
    perimeters: geopandas.GeoDataFrame,
    points: geopandas.GeoDataFrame,
    differential_perimeters: geopandas.GeoDataFrame,
    scores: peri_scribe.models.FireScores | None = None,
    *,
    incident_rows: geopandas.GeoDataFrame | None = None,
    histories: typing.Mapping[
        peri_scribe.presentation.selection.AreaKey,
        peri_scribe.areas.PreparedHistory,
    ]
    | None = None,
) -> list[PreparedFire]:
    """Prepare shared fire facts and history evidence in index order.

    A fire's point is its last known location or a representative point of its latest
    perimeter. Score explanations resolve by identifier, then by name.

    Args:
        index: Fire identities and current status.
        perimeters: The full perimeter history layer.
        points: The point history layer.
        differential_perimeters: Differential growth rings.
        scores: Saved scores and explanations, when available.
        incident_rows: The optional independent reporting history.
        histories: Already prepared histories keyed by canonical fire identity.

    Returns:
        One prepared summary and its source evidence per indexed fire.
    """
    notes_by_identifier = (
        {
            entry.identifier: entry.explanation
            for entry in scores.fires
            if entry.identifier is not None
        }
        if scores is not None
        else {}
    )
    notes_by_name = (
        {
            entry.name: entry.explanation
            for entry in scores.fires
            if entry.identifier is None
        }
        if scores is not None
        else {}
    )
    perimeter_by_identifier, perimeter_by_name = (
        peri_scribe.presentation.selection.perimeter_groups(perimeters)
    )
    ring_by_identifier, ring_by_name = (
        peri_scribe.presentation.selection.perimeter_groups(
            differential_perimeters,
        )
    )
    point_by_identifier, point_by_name = (
        peri_scribe.presentation.selection.point_locations(
            points,
        )
    )
    pending = prepare_fires(
        index=index,
        perimeters=perimeters,
        points=points,
        perimeter_by_identifier=perimeter_by_identifier,
        perimeter_by_name=perimeter_by_name,
        ring_by_identifier=ring_by_identifier,
        ring_by_name=ring_by_name,
        incident_rows=incident_rows,
        histories=histories,
    )
    fires: list[PreparedFire] = []
    for prepared in pending:
        perimeter_rows = peri_scribe.presentation.history_index.select_rows(
            perimeters,
            prepared.perimeter_positions,
        )
        point_rows = peri_scribe.presentation.history_index.select_rows(
            points,
            prepared.point_positions,
        )
        fires.append(
            PreparedFire(
                summary=FireSummary(
                    name=prepared.entry.name,
                    status=peri_scribe.models.FireStatus(prepared.entry.status),
                    point=peri_scribe.presentation.selection.fire_point_location(
                        prepared.identifiers,
                        prepared.entry.name,
                        point_by_identifier,
                        point_by_name,
                        prepared.perimeters,
                    ),
                    perimeters=prepared.perimeters,
                    progression_rings=prepared.progression_rings,
                    identifiers=prepared.identifiers,
                    description=peri_scribe.presentation.text.fire_description(
                        prepared.entry,
                        perimeter_rows,
                        point_rows,
                        history=prepared.history,
                        of_note=peri_scribe.presentation.text.score_explanation_for(
                            notes_by_identifier,
                            notes_by_name,
                            prepared.identifiers,
                            prepared.entry.name,
                        ),
                    ),
                    type_one=peri_scribe.fires.scoring.fire_is_type_one_incident(
                        point_rows,
                    ),
                ),
                identifier=prepared.entry.identifier,
                history=prepared.history,
                perimeter_positions=prepared.perimeter_positions,
                point_positions=prepared.point_positions,
            ),
        )
    return fires


def optional_history_index(
    frame: geopandas.GeoDataFrame | None,
) -> peri_scribe.presentation.history_index.HistoryRowIndex | None:
    """Keep independent incident history optional for geography-only inputs.

    Args:
        frame: The reporting layer, if available.

    Returns:
        An index for a populated frame, or None so callers can use fallback sources.
    """
    return (
        None
        if frame is None or frame.empty
        else peri_scribe.presentation.history_index.HistoryRowIndex.from_frame(frame)
    )


def selected_incidents(
    frame: geopandas.GeoDataFrame | None,
    index: peri_scribe.presentation.history_index.HistoryRowIndex | None,
    identifiers: frozenset[str],
    name: str,
) -> geopandas.GeoDataFrame | None:
    """Select a fire's reports using the identity rules shared with its geography.

    Args:
        frame: The optional independent incident-history layer.
        index: The row index for that layer, if it is available.
        identifiers: Identifiers and aliases associated with this fire.
        name: The fire name used when identifiers do not resolve its history.

    Returns:
        The matching report rows, possibly empty, or None without an indexed layer.
    """
    if frame is None or index is None:
        return None
    return peri_scribe.presentation.history_index.select_rows(
        frame,
        index.positions_for(identifiers, name),
    )


def fire_summaries(
    index: peri_scribe.models.FireIndex,
    perimeters: geopandas.GeoDataFrame,
    points: geopandas.GeoDataFrame,
    differential_perimeters: geopandas.GeoDataFrame,
    scores: peri_scribe.models.FireScores | None = None,
    *,
    incident_rows: geopandas.GeoDataFrame | None = None,
    histories: typing.Mapping[
        peri_scribe.presentation.selection.AreaKey,
        peri_scribe.areas.PreparedHistory,
    ]
    | None = None,
) -> list[FireSummary]:
    """Return the shared fire facts in case-insensitive name order.

    Args:
        index: Fire identities and current status.
        perimeters: The full perimeter history layer.
        points: The point history layer.
        differential_perimeters: Differential growth rings.
        scores: Saved scores and explanations, when available.
        incident_rows: The optional independent reporting history.
        histories: Already prepared histories keyed by canonical fire identity.

    Returns:
        One summary per indexed fire, sorted by name.
    """
    prepared = prepare_fire_data(
        index,
        perimeters,
        points,
        differential_perimeters,
        scores,
        incident_rows=incident_rows,
        histories=histories,
    )
    return sorted((fire.summary for fire in prepared), key=fire_name_key)
