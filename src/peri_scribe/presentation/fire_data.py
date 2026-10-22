"""Prepare fire summaries and history evidence shared by output formats.

[Algorithm note](../../../docs/algorithms/presentation-selection.md)

Design notes:
[Incident area selection](../../../docs/algorithms/incident-area-selection.md).
"""

from __future__ import annotations

import dataclasses
import hashlib
import typing

import peri_scribe.areas
import peri_scribe.execution
import peri_scribe.fires.scoring
import peri_scribe.history_columns
import peri_scribe.models
import peri_scribe.perimeters.progression
import peri_scribe.presentation.descriptions
import peri_scribe.presentation.history_index
import peri_scribe.presentation.perimeters
import peri_scribe.presentation.prepared_cache
import peri_scribe.presentation.score_association
import peri_scribe.presentation.selection
import peri_scribe.presentation.text
import spatial_data.cache_values
import spatial_data.frame_fingerprints
import spatial_data.product_cache


if typing.TYPE_CHECKING:
    import geopandas
    import shapely


@dataclasses.dataclass(frozen=True, kw_only=True)
class FireSummary:
    """One fire's identity, latest facts, location, and perimeter history.

    These values give reports and maps the same basis for ranking and descriptions.
    ``type_one`` reflects the latest point-history designation used by scoring. Internal
    component keys preserve source ownership without becoming external identifiers.
    """

    name: str
    status: peri_scribe.models.FireStatus
    point: shapely.Point | None
    perimeters: tuple[peri_scribe.presentation.perimeters.Perimeter, ...]
    progression_rings: tuple[peri_scribe.perimeters.progression.Ring, ...] = ()
    description: peri_scribe.presentation.descriptions.FireDescription | None = None
    identifiers: frozenset[str] = frozenset()
    component_id: str | None = None
    component_aliases: frozenset[str] = frozenset()
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

    Folding case lets each view sort names without treating uppercase and lowercase
    spellings as different letters. Names that differ only in case have the same key.

    Args:
        named: The fire to key.

    Returns:
        The fire's case-folded name.
    """
    return named.name.casefold()


def descending_value_name_key(ranked: tuple[FireSummary, float]) -> tuple[float, str]:
    """Return the ordering key that ranks fires by value, then by name.

    The largest value comes first. Ties compare names without regard to case; equal name
    keys retain their input order when sorted.

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

    The ring's polygon surface area controls the growth window and colors. Prepared
    measurements and standalone geometry use the same straight-edge surface policy.

    Args:
        perimeter: The differential perimeter to turn into a ring.

    Returns:
        The ring, or None when its area is at most one square meter.
    """
    policy_prefix = f"{peri_scribe.perimeters.progression.MEASUREMENT_POLICY}:"
    area = (
        perimeter.area
        if perimeter.area is not None
        and (perimeter.sequence_digest or "").startswith(policy_prefix)
        else peri_scribe.perimeters.progression.covered_area(perimeter.geometry)
    )
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
    return tuple(
        sorted(
            perimeters,
            key=lambda perimeter: (
                perimeter.observation_time is not None,
                perimeter.observation_time,
            ),
        ),
    )


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
        history: Complete prepared reporting and area evidence for this fire.
    """

    entry: peri_scribe.models.FireIndexEntry
    identifiers: frozenset[str]
    perimeters: tuple[peri_scribe.presentation.perimeters.Perimeter, ...]
    progression_rings: tuple[peri_scribe.perimeters.progression.Ring, ...]
    perimeter_positions: tuple[int, ...]
    point_positions: tuple[int, ...]
    history: peri_scribe.areas.PreparedHistory


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
    perimeter_by_component: typing.Mapping[
        str,
        tuple[peri_scribe.presentation.perimeters.Perimeter, ...],
    ]
    | None = None,
    ring_by_component: typing.Mapping[
        str,
        tuple[peri_scribe.presentation.perimeters.Perimeter, ...],
    ]
    | None = None,
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
        perimeter_by_component: Exact source-component mapping observations.
        ring_by_component: Exact source-component differential observations.
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
        if entry.component_id is not None:
            perimeter_observations = (perimeter_by_component or {}).get(
                entry.component_id,
                (),
            )
            ring_observations = (ring_by_component or {}).get(entry.component_id, ())
        else:
            perimeter_observations = fire_perimeters(
                fire_identifiers,
                entry.name,
                perimeter_by_identifier,
                perimeter_by_name,
            )
            ring_observations = fire_perimeters(
                fire_identifiers,
                entry.name,
                ring_by_identifier,
                ring_by_name,
            )
        progression_rings = tuple(
            ring
            for observation in ring_observations
            if (ring := progression_ring(observation)) is not None
        )
        perimeter_positions = perimeter_index.positions_for(
            fire_identifiers,
            entry.name,
            entry.component_id,
        )
        point_positions = point_index.positions_for(
            fire_identifiers,
            entry.name,
            entry.component_id,
        )
        history = (
            None
            if histories is None
            else histories.get(
                peri_scribe.presentation.selection.fire_area_key(
                    entry.identifier,
                    entry.name,
                    entry.component_id,
                ),
            )
        )
        if history is None:
            perimeter_rows = peri_scribe.presentation.history_index.select_rows(
                perimeters,
                perimeter_positions,
            )
            point_rows = peri_scribe.presentation.history_index.select_rows(
                points,
                point_positions,
            )
            history = peri_scribe.areas.prepare_history(
                perimeter_rows,
                point_rows,
                selected_incidents(
                    incident_rows,
                    incident_index,
                    fire_identifiers,
                    entry.name,
                    entry.component_id,
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


@dataclasses.dataclass(frozen=True, kw_only=True)
class SharedFires:
    """Keep source objects alive while maps and reports share their fire facts."""

    sources: tuple[object, ...]
    fires: list[PreparedFire]


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
    perimeter. Score explanations resolve by identifier, then by component; only scores
    without a component can fall back to a name.

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
    sources = (perimeters, points, differential_perimeters, incident_rows, histories)
    key = (
        (
            "prepared_fire_data",
            peri_scribe.presentation.prepared_cache.document_digest(index),
            None
            if scores is None
            else peri_scribe.presentation.prepared_cache.document_digest(scores),
            tuple(map(id, sources)),
        )
        if peri_scribe.execution.active()
        else None
    )
    shared = peri_scribe.execution.get(peri_scribe.execution.Group.PRESENTATION, key)
    if isinstance(shared, SharedFires) and all(
        previous is current
        for previous, current in zip(shared.sources, sources, strict=True)
    ):
        return shared.fires
    perimeter_indexes = peri_scribe.presentation.selection.perimeter_indexes(perimeters)
    ring_indexes = peri_scribe.presentation.selection.perimeter_indexes(
        differential_perimeters,
    )
    point_indexes = peri_scribe.presentation.selection.point_indexes(points)
    pending = prepare_fires(
        index=index,
        perimeters=perimeters,
        points=points,
        perimeter_by_identifier=perimeter_indexes.by_identifier,
        perimeter_by_name=perimeter_indexes.by_name,
        ring_by_identifier=ring_indexes.by_identifier,
        ring_by_name=ring_indexes.by_name,
        perimeter_by_component=perimeter_indexes.by_component,
        ring_by_component=ring_indexes.by_component,
        incident_rows=incident_rows,
        histories=histories,
    )
    associated = (
        peri_scribe.presentation.score_association.associated_scores(
            tuple((fire.entry.name, fire.identifiers) for fire in pending),
            scores,
            component_ids=tuple(fire.entry.component_id for fire in pending),
        )
        if scores is not None
        else {}
    )
    columns = tuple(
        peri_scribe.history_columns.prepare_source(frame)
        for frame in (perimeters, points)
    )
    schemas = description_schemas((perimeters, points))
    fires: list[PreparedFire] = []
    for position, prepared in enumerate(pending):
        perimeter_rows = peri_scribe.history_columns.select_rows(
            columns[0],
            prepared.perimeter_positions[-1:],
        )
        point_rows = peri_scribe.history_columns.select_rows(
            columns[1],
            prepared.point_positions[-1:],
        )
        fingerprints = latest_row_fingerprints((perimeter_rows, point_rows), schemas)
        local_points = (
            point_indexes.by_component.get(prepared.entry.component_id, ({}, {}))
            if prepared.entry.component_id is not None
            else (point_indexes.by_identifier, point_indexes.by_name)
        )
        fires.append(
            PreparedFire(
                summary=FireSummary(
                    name=prepared.entry.name,
                    status=peri_scribe.models.FireStatus(prepared.entry.status),
                    point=peri_scribe.presentation.selection.fire_point_location(
                        prepared.identifiers,
                        prepared.entry.name,
                        *local_points,
                        prepared.perimeters,
                    ),
                    perimeters=prepared.perimeters,
                    progression_rings=prepared.progression_rings,
                    identifiers=prepared.identifiers,
                    component_id=prepared.entry.component_id,
                    component_aliases=frozenset(prepared.entry.component_aliases),
                    description=peri_scribe.presentation.text.fire_description(
                        prepared.entry,
                        perimeter_rows,
                        point_rows,
                        history=prepared.history,
                        row_fingerprints=fingerprints,
                        of_note=(
                            associated[position].explanation
                            if position in associated
                            else None
                        ),
                    ),
                    type_one=latest_type_one(point_rows),
                ),
                identifier=prepared.entry.identifier,
                history=prepared.history,
                perimeter_positions=prepared.perimeter_positions,
                point_positions=prepared.point_positions,
            ),
        )
    peri_scribe.execution.put(
        peri_scribe.execution.Group.PRESENTATION,
        key,
        SharedFires(sources=sources, fires=fires),
    )
    return fires


def description_schemas(
    frames: tuple[geopandas.GeoDataFrame, ...],
) -> tuple[bytes, ...]:
    """Prepare complete schema evidence only when a cache can consume it.

    Args:
        frames: Complete unchanged source layers for this description preparation.

    Returns:
        Schema digests, or an empty tuple when caching is inactive or unsupported.
    """
    if not spatial_data.product_cache.active():
        return ()
    try:
        return tuple(
            spatial_data.frame_fingerprints.frame_schema(frame) for frame in frames
        )
    except ValueError:
        return ()


def latest_row_fingerprints(
    rows: tuple[peri_scribe.history_columns.Frame, ...],
    schemas: tuple[bytes, ...],
) -> tuple[spatial_data.frame_fingerprints.FrameRows, ...] | None:
    """Carry current row identities directly from shared source columns.

    Args:
        rows: Latest-row views from this preparation call.
        schemas: Complete source schema digests, or none when caching is inactive.

    Returns:
        Exact current schema and row evidence, or None for unsupported cache scalars.
    """
    if not schemas:
        return None
    try:
        return tuple(
            spatial_data.frame_fingerprints.FrameRows(
                schema=schema,
                rows=tuple(
                    hashlib.sha256(
                        spatial_data.cache_values.dumps(
                            tuple(
                                values[position]
                                for values in frame.columns.fields.values()
                            ),
                        ),
                    ).digest()
                    for position in frame.positions
                )
                if not frame.empty
                else (),
            )
            if isinstance(frame, peri_scribe.history_columns.HistoryRows)
            else spatial_data.frame_fingerprints.frame_rows(
                typing.cast("geopandas.GeoDataFrame", frame),
            )
            for frame, schema in zip(rows, schemas, strict=True)
        )
    except ValueError:
        return None


def latest_type_one(points: peri_scribe.history_columns.Frame) -> bool:
    """Apply the existing scoring designation to the latest borrowed point row.

    Args:
        points: This fire's selected latest point evidence.

    Returns:
        Whether that row carries the Type 1 Incident designation.
    """
    if points.empty:
        return False
    row = peri_scribe.history_columns.last_row(points)
    return (
        peri_scribe.fires.scoring.importance_points(
            peri_scribe.fires.scoring.complexity_level(row.get("source_attributes")),
        )
        == peri_scribe.fires.scoring.IMPORTANCE_POINTS_BY_LEVEL["Type 1 Incident"]
    )


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
    component_id: str | None = None,
) -> geopandas.GeoDataFrame | None:
    """Select a fire's reports using the identity rules shared with its geography.

    Args:
        frame: The optional independent incident-history layer.
        index: The row index for that layer, if it is available.
        identifiers: Identifiers and aliases associated with this fire.
        name: The fire name used only when both identifiers and component_id are absent.
        component_id: The exact source component, when recorded in derived history.

    Returns:
        The matching report rows, possibly empty, or None without an indexed layer.
    """
    if frame is None or index is None:
        return None
    return peri_scribe.presentation.history_index.select_rows(
        frame,
        index.positions_for(identifiers, name, component_id),
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
