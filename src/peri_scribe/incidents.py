"""Incident reports have their own clock, independent of mapped polygons."""

from __future__ import annotations

import dataclasses
import datetime
import itertools
import json
import typing

import peri_scribe.geo.parsing


if typing.TYPE_CHECKING:
    import pandas as pd


LAYER_NAME = "incident_history"
VALUE_COLUMNS = (
    "incident_size",
    "estimated_cost_to_date",
    "estimated_final_cost",
    "personnel",
    "percent_contained",
)
ATTRIBUTE_KEYS = (
    "IncidentSize",
    "EstimatedCostToDate",
    "EstimatedFinalCost",
    "TotalIncidentPersonnel",
    "PercentContained",
)


@dataclasses.dataclass(frozen=True, kw_only=True)
class IncidentUpdate:
    """Preserve incident-report evidence independently of perimeter capture times.

    Attributes:
        observation_time: When the incident attributes were updated.
        report_time: The associated formal report time, when supplied.
        confirmed: Whether the source identifies this update as a formal ICS-209 report
            rather than an ordinary incident edit.
        source: The feed supplying the attributes.
        source_file: The snapshot supporting the update.
        serial: The snapshot sequence used to resolve publication ties.
        measurements: Available fields in their source units: acres, dollars, personnel
            counts, and containment percentages from zero to one hundred.
    """

    observation_time: datetime.datetime
    report_time: datetime.datetime | None
    confirmed: bool
    source: str
    source_file: str
    serial: int
    measurements: dict[str, float]


def attributes_dictionary(value: object) -> dict[str, object]:
    """Allow source attributes to survive either in-memory or serialized storage.

    Args:
        value: An attribute dictionary, its JSON representation, or missing data.

    Returns:
        The attribute dictionary, or an empty dictionary for unusable input.
    """
    if isinstance(value, dict):
        return value
    if isinstance(value, str):
        try:
            decoded = json.loads(value)
        except json.JSONDecodeError:
            return {}
        if isinstance(decoded, dict):
            return decoded
    return {}


def update_from_row(row: pd.Series, *, perimeter: bool) -> IncidentUpdate | None:
    """Keep incident measurements on their own clock when supplied beside a polygon.

    Perimeter attributes need an incident modification time; a polygon's observation
    time does not date its attached report. Normalized incident rows retain their
    recorded timing and confirmation. Zero measurements remain meaningful, while
    missing, nonnumeric, and negative values cannot support a metric.

    Args:
        row: A source history row or a normalized incident-history row.
        perimeter: Whether raw attributes came from a perimeter feed and require its
            incident attribute prefix and modification timestamp.

    Returns:
        A dated incident update with available measurements and provenance, or None when
        no usable incident observation time is present.
    """
    attributes = attributes_dictionary(row.get("source_attributes"))
    prefix = "attr_" if perimeter else ""
    normalized = "report_confirmed" in row.index
    time = peri_scribe.geo.parsing.observation_time_from(
        row.get("observation_time")
        if normalized or not perimeter
        else attributes.get("attr_ModifiedOnDateTime_dt", row.get("modified_time")),
    )
    if time is None:
        return None
    report_time = peri_scribe.geo.parsing.observation_time_from(
        row.get("report_time")
        if normalized
        else attributes.get(prefix + "ICS209ReportDateTime"),
    )
    values: dict[str, float] = {}
    for column, key in zip(VALUE_COLUMNS, ATTRIBUTE_KEYS, strict=True):
        raw = row.get(column) if normalized else attributes.get(prefix + key)
        # A perimeter's derived acreage cannot stand in for an incident report.
        if raw is None and (not perimeter or column != "incident_size"):
            raw = row.get(column)
        number = peri_scribe.geo.parsing.numeric_value(raw)
        if number is not None and number >= 0:
            values[column] = number
    confirmed = (
        bool(row["report_confirmed"])
        if normalized
        else str(attributes.get(prefix + "ModifiedBySystem", "")).casefold() == "ics209"
        and report_time is not None
    )
    return IncidentUpdate(
        observation_time=time,
        report_time=report_time,
        confirmed=confirmed,
        source=str(
            row.get("source", "wfigs_perimeter" if perimeter else "wfigs_location"),
        ),
        source_file=str(row.get("source_file", "")),
        serial=int(
            peri_scribe.geo.parsing.numeric_value(row.get("source_serial")) or 0,
        ),
        measurements=values,
    )


def simultaneous_updates(
    updates: typing.Iterable[IncidentUpdate],
) -> tuple[IncidentUpdate, ...]:
    """Keep each winning measurement attached to the report that supports it.

    Direct incident fields win conflicting values. Identical values can retain the
    newest formal confirmation from either feed. Measurements with different evidence
    remain separate updates at the same instant so storage preserves their provenance.

    Args:
        updates: Simultaneous updates ordered from lowest to highest feed priority.

    Returns:
        Updates containing disjoint measurement fields and their supporting metadata.
    """
    ordered = tuple(updates)
    winners: dict[str, IncidentUpdate] = {}
    for update in ordered:
        for column, value in update.measurements.items():
            previous = winners.get(column)
            previous_time = (
                previous.report_time
                if previous is not None and previous.confirmed
                else None
            )
            current_time = update.report_time if update.confirmed else None
            if (
                previous is not None
                and previous.measurements[column] == value
                and previous_time is not None
                and (current_time is None or previous_time > current_time)
            ):
                continue
            winners[column] = update
    winning_ids = {id(winner) for winner in winners.values()}
    return tuple(
        dataclasses.replace(
            update,
            measurements={
                column: update.measurements[column]
                for column, winner in winners.items()
                if winner is update
            },
        )
        for update in {
            id(item): item for item in ordered if id(item) in winning_ids
        }.values()
    )


def reconcile_updates(
    updates: typing.Iterable[IncidentUpdate],
) -> tuple[IncidentUpdate, ...]:
    """Resolve duplicate reports and stale edits without discarding newer evidence.

    Direct incident fields win simultaneous feed conflicts, with missing fields filled
    from the other update. An unconfirmed edit citing an unchanged or older formal
    report cannot undo confirmed values. Newly reported acreage growth remains eligible
    between formal reports, and newer reporting evidence can make corrections.

    Args:
        updates: Incident updates from any supported feed, in any order.

    Returns:
        Chronological updates with each measurement's source and confirmation retained.
        Separate supporting reports can share an observation time.
    """
    # Both feeds can carry the same IRWIN report; direct incident fields win ties.
    ordered = sorted(
        updates,
        key=lambda item: (
            item.observation_time,
            item.source == "wfigs_location",
            item.serial,
            item.source_file,
        ),
    )
    merged = (
        update
        for _time, group in itertools.groupby(
            ordered,
            key=lambda item: item.observation_time,
        )
        for update in simultaneous_updates(group)
    )
    result: list[IncidentUpdate] = []
    confirmed_values: dict[str, tuple[datetime.datetime, float]] = {}
    for update in merged:
        values = dict(update.measurements)
        for column, (report_time, value) in confirmed_values.items():
            area_growth = (
                column == "incident_size" and values.get(column, value) > value
            )
            if (
                not update.confirmed
                and update.report_time is not None
                and update.report_time <= report_time
                and column in values
                and not area_growth
            ):
                # Dispatch edits can restore old values, but newly reported acreage
                # growth can be useful before the next formal incident report.
                values[column] = value
        if update.confirmed and update.report_time is not None:
            confirmed_values.update({
                column: (update.report_time, value) for column, value in values.items()
            })
        result.append(dataclasses.replace(update, measurements=values))
    return tuple(result)


def history(
    perimeters: pd.DataFrame,
    points: pd.DataFrame,
    incident_rows: pd.DataFrame | None = None,
) -> tuple[IncidentUpdate, ...]:
    """Prefer independent reporting history so polygon selection cannot erase reports.

    Geography-only inputs remain usable through their attached incident attributes when
    a populated independent incident layer is unavailable.

    Args:
        perimeters: Perimeter rows that may carry incident attributes.
        points: Incident location rows available as fallback reporting evidence.
        incident_rows: The optional normalized incident history for this fire.

    Returns:
        Reconciled incident updates in chronological order.
    """
    frames = (
        ((incident_rows, False),)
        if incident_rows is not None and not incident_rows.empty
        else ((perimeters, True), (points, False))
    )
    return reconcile_updates(
        update
        for frame, perimeter in frames
        for _, row in frame.iterrows()
        if (update := update_from_row(row, perimeter=perimeter)) is not None
    )


def latest_value(updates: tuple[IncidentUpdate, ...], column: str) -> float | None:
    """Keep the latest known measurement when later updates omit that field.

    Args:
        updates: Reconciled incident updates in chronological order.
        column: The normalized measurement field to look up.

    Returns:
        The latest supplied value in its source units, or None if never supplied.
    """
    return next(
        (
            update.measurements[column]
            for update in reversed(updates)
            if column in update.measurements
        ),
        None,
    )
