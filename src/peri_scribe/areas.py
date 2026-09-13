"""A shared area estimate follows mapping until incident reports outgrow it."""

from __future__ import annotations

import dataclasses
import datetime
import enum
import operator
import typing

import peri_scribe.geo.measurements
import peri_scribe.geo.parsing
import peri_scribe.incidents
import peri_scribe.units
from peri_scribe.units import units


if typing.TYPE_CHECKING:
    import pandas as pd
    import pint
    import shapely


@dataclasses.dataclass(frozen=True, kw_only=True)
class AreaPolicy:
    """Balance mapped accuracy against growth reported between surveys.

    Age and growth thresholds prevent routine report edits from displacing a recent
    mapping. Repeated formal reports can establish rapid growth sooner. Footprint
    thresholds keep negligible geometry edits from renewing the survey's freshness.

    Attributes:
        stale_after: Mapping age at which ordinary reported growth can take over.
        rapid_after: Minimum mapping age for corroborated rapid growth to take over.
        significant_ratio: Relative growth needed for ordinary takeover; also limits
            unconfirmed decreases between accepted acreage reports.
        rapid_ratio: Relative growth required in the rapid-growth reports.
        rapid_confirmations: Distinct formal report times required for rapid growth.
        minimum_increase: Absolute acreage change required alongside a report ratio.
        footprint_fraction: Minimum changed fraction of the preceding survey's area that
            counts as a fresh mapping without new capture evidence.
        minimum_footprint_change: Absolute footprint change required alongside that
            fraction, so small geometry edits do not count as new surveys.
    """

    stale_after: datetime.timedelta = datetime.timedelta(days=3)
    rapid_after: datetime.timedelta = datetime.timedelta(days=1)
    significant_ratio: float = 1.25
    rapid_ratio: float = 2.0
    rapid_confirmations: int = 2
    minimum_increase: pint.Quantity[float] = 10.0 * units.acres
    footprint_fraction: float = 0.01
    minimum_footprint_change: pint.Quantity[float] = 1.0 * units.acres


DEFAULT_POLICY = AreaPolicy()


class AreaSource(enum.StrEnum):
    """Distinguish geometry measurements from incident-reported acreage."""

    MAPPED = "Mapped"
    REPORTED = "Reported"


@dataclasses.dataclass(frozen=True, kw_only=True)
class AreaEstimate:
    """Keep a selected acreage traceable to its evidence and effective time.

    A policy deadline can make a report effective after it was observed, so those two
    times must remain separate for chart placement and source attribution.

    Attributes:
        time: When this estimate applies in the selected history.
        observation_time: When the supporting mapping or report was observed.
        area: An area-dimension quantity without a canonical storage unit. Mappings
            supply square meters and reports supply acres; consumers must convert.
        source: Whether geometry or an incident report supplies the area.
        source_file: The snapshot supporting this estimate.
    """

    time: datetime.datetime
    observation_time: datetime.datetime
    area: pint.Quantity[float]
    source: AreaSource
    source_file: str


@dataclasses.dataclass(frozen=True, kw_only=True)
class Mapping:
    """Retain geometry evidence without treating every publication as a new survey.

    Attributes:
        time: The perimeter observation time.
        area: The geometry's measured area in square meters, retained as a quantity so
            consumers can convert to their desired area unit.
        geometry: The footprint used to assess meaningful changes between mappings.
        source_file: The snapshot supporting this mapping.
        surveyed: Whether this observation renews the mapping's freshness for area
            selection through capture evidence or a significant footprint change.
    """

    time: datetime.datetime
    area: pint.Quantity[float]
    geometry: shapely.Geometry
    source_file: str
    surveyed: bool


@dataclasses.dataclass(frozen=True, kw_only=True)
class PreparedHistory:
    """Share one fire's reporting and area decisions across output consumers.

    Attributes:
        updates: Reconciled incident measurements with their supporting metadata.
        estimates: Selected area estimates in chronological order.
        latest_area: Current size, including sparse-record fallbacks, if available.
        historical_area: Largest qualifying estimate or sparse-record fallback.
    """

    updates: tuple[peri_scribe.incidents.IncidentUpdate, ...]
    estimates: tuple[AreaEstimate, ...]
    latest_area: pint.Quantity[float] | None
    historical_area: pint.Quantity[float] | None


def prepare_history(
    perimeters: pd.DataFrame,
    points: pd.DataFrame,
    incident_rows: pd.DataFrame | None = None,
) -> PreparedHistory:
    """Reconcile each fire once so qualification, charts, and text share its evidence.

    Args:
        perimeters: The fire's perimeter observations and measurements.
        points: Its incident location history and fallback acreage fields.
        incident_rows: The optional independent reporting history.

    Returns:
        Reconciled reports, selected area history, and current and historical acreage.
    """
    updates = peri_scribe.incidents.history(perimeters, points, incident_rows)
    estimates = area_history(perimeters, points, incident_rows, updates=updates)
    return PreparedHistory(
        updates=updates,
        estimates=estimates,
        latest_area=latest_area(perimeters, points, incident_rows, history=estimates),
        historical_area=historical_area(
            perimeters,
            points,
            incident_rows,
            history=estimates,
        ),
    )


def row_area(row: pd.Series) -> pint.Quantity[float] | None:
    """Require usable geometry before treating a row as a mapped area.

    Args:
        row: A perimeter row with geometry and, optionally, its stored measurement.

    Returns:
        The positive measured area, using the stored geometry measurement when
        available, or None for missing, empty, or zero-area geometry.
    """
    geometry = row.get("geometry")
    if geometry is None or geometry.is_empty:
        return None
    measured = peri_scribe.geo.measurements.area(
        geometry,
        row.get(peri_scribe.geo.measurements.AREA_COLUMN),
    )
    return measured if measured > 0 * units.acres else None


def new_survey(row: pd.Series, previous_time: datetime.datetime | None) -> bool:
    """Recognize survey evidence that can renew an unchanged footprint's freshness.

    Flight observations establish survey activity directly. Other sources need a
    plausible capture date newer than the preceding survey observation; an ordinary
    publication edit alone does not establish a new survey.

    Args:
        row: The candidate perimeter row and its source attributes.
        previous_time: The preceding survey's observation time, if one exists.

    Returns:
        Whether the source or capture metadata establishes a new survey.
    """
    if str(row.get("source_subsource", "")) in {"FIRIS", "CAL FIRE INTEL FLIGHT DATA"}:
        return True
    attributes = peri_scribe.incidents.attributes_dictionary(
        row.get("source_attributes"),
    )
    capture = peri_scribe.geo.parsing.observation_time_from(
        attributes.get("poly_PolygonDateTime"),
    )
    current = peri_scribe.geo.parsing.observation_time_from(row.get("observation_time"))
    return (
        capture is not None
        and current is not None
        and capture.year == current.year
        and capture <= current
        and (previous_time is None or capture > previous_time)
    )


def mapping_history(
    perimeters: pd.DataFrame,
    policy: AreaPolicy,
) -> tuple[Mapping, ...]:
    """Separate useful mapping observations from evidence of a fresh survey.

    Repeated publications remain available as measurements, but only survey evidence or
    a sufficiently changed footprint renews freshness. This lets reports take over when
    a source keeps republishing a stagnant boundary.

    Args:
        perimeters: The fire's perimeter rows, including geometry and provenance.
        policy: The relative and absolute footprint-change thresholds.

    Returns:
        Dated, positive-area mappings in chronological order, marked with whether each
        observation counts as a fresh survey.
    """
    rows = sorted(
        (
            (time, row)
            for _, row in perimeters.iterrows()
            if (
                time := peri_scribe.geo.parsing.observation_time_from(
                    row.get("observation_time"),
                )
            )
            is not None
        ),
        key=operator.itemgetter(0),
    )
    previous: Mapping | None = None
    result: list[Mapping] = []
    for time, row in rows:
        area = row_area(row)
        if area is None:
            continue
        geometry = row.geometry
        surveyed = previous is None or new_survey(row, previous.time)
        if not surveyed and previous is not None:
            difference = peri_scribe.units.area(
                geometry.symmetric_difference(previous.geometry),
            )
            surveyed = difference >= max(
                policy.minimum_footprint_change,
                previous.area * policy.footprint_fraction,
            )
        mapping = Mapping(
            time=time,
            area=area,
            geometry=geometry,
            source_file=str(row.get("source_file", "")),
            surveyed=surveyed,
        )
        result.append(mapping)
        if surveyed:
            previous = mapping
    return tuple(result)


def report_can_take_over(
    mapping: Mapping,
    reports: tuple[peri_scribe.incidents.IncidentUpdate, ...],
    time: datetime.datetime,
    baseline: float | None,
    policy: AreaPolicy,
) -> bool:
    """Require evidence of subsequent growth before reports displace a mapping.

    Ordinary growth must outlast the staleness threshold. Rapid growth can qualify
    sooner when distinct formal reports corroborate it. Both routes require an absolute
    increase and growth beyond any report already known at the survey.

    Args:
        mapping: The latest mapping that established survey freshness.
        reports: Accepted acreage reports known at time, in chronological order.
        time: The observation or policy deadline at which to assess eligibility.
        baseline: Reported acreage known at the survey, in acres, or None.
        policy: The mapping-age, growth, and corroboration requirements.

    Returns:
        Whether the latest report qualifies to replace the mapped estimate.
    """
    if not reports:
        return False
    report = reports[-1]
    value = report.measurements["incident_size"] * units.acres
    if report.observation_time <= mapping.time or (
        baseline is not None and value <= baseline * units.acres
    ):
        return False
    if value - mapping.area < policy.minimum_increase:
        return False
    age = time - mapping.time
    if age >= policy.stale_after and value >= mapping.area * policy.significant_ratio:
        return True
    confirmations = {
        item.report_time
        for item in reports
        if item.confirmed
        and item.observation_time > mapping.time
        and item.measurements["incident_size"] * units.acres
        >= mapping.area * policy.rapid_ratio
    }
    return (
        age >= policy.rapid_after
        and value >= mapping.area * policy.rapid_ratio
        and len(confirmations) >= policy.rapid_confirmations
    )


def accepted_reports(
    updates: tuple[peri_scribe.incidents.IncidentUpdate, ...],
    policy: AreaPolicy,
) -> tuple[peri_scribe.incidents.IncidentUpdate, ...]:
    """Keep unsupported report reversions from driving area selection.

    Large decreases need formal report confirmation, while smaller adjustments and
    explicitly confirmed corrections remain eligible.

    Args:
        updates: Reconciled incident updates in chronological order.
        policy: The relative and absolute thresholds for an unconfirmed decrease.

    Returns:
        Updates containing accepted incident acreage, preserving their order.
    """
    result: list[peri_scribe.incidents.IncidentUpdate] = []
    for update in updates:
        value = update.measurements.get("incident_size")
        if value is None:
            continue
        if result and not update.confirmed:
            previous = result[-1].measurements["incident_size"]
            if (
                value * policy.significant_ratio < previous
                and (previous - value) * units.acres >= policy.minimum_increase
            ):
                continue
        result.append(update)
    return tuple(result)


def area_history(
    perimeters: pd.DataFrame,
    points: pd.DataFrame,
    incident_rows: pd.DataFrame | None = None,
    *,
    policy: AreaPolicy = DEFAULT_POLICY,
    updates: tuple[peri_scribe.incidents.IncidentUpdate, ...] | None = None,
) -> tuple[AreaEstimate, ...]:
    """Provide one source-attributed area history for charts, scores, and descriptions.

    Geometry leads while mapping is fresh. Reports supply area without mapping and can
    take over when subsequent growth satisfies the policy. A fresh mapping restores
    geometry, including legitimate downward corrections. Policy deadlines within the
    observed history expose eligible growth even without another feed edit.

    Args:
        perimeters: The fire's perimeter history with geometry and source metadata.
        points: Incident location rows used when independent reports are unavailable.
        incident_rows: The optional independent incident history.
        policy: The freshness, growth, and corroboration rules for selecting area.
        updates: Already reconciled incident updates, or None to read them.

    Returns:
        Chronological estimates with separate effective and evidence times, or an empty
        tuple when no dated mapping or accepted acreage report is available.
    """
    mappings = mapping_history(perimeters, policy)
    if updates is None:
        updates = peri_scribe.incidents.history(perimeters, points, incident_rows)
    reports = accepted_reports(updates, policy)
    if not mappings and not reports:
        return ()
    mapping_by_time = {mapping.time: mapping for mapping in mappings}
    report_by_time = {report.observation_time: report for report in reports}
    times = set(mapping_by_time) | set(report_by_time)
    last_time = max(times)
    # Deadlines expose already-reported growth when no further feed edits arrive.
    times.update(
        mapping.time + delay
        for mapping in mappings
        for delay in (policy.stale_after, policy.rapid_after)
        if mapping.time + delay <= last_time
    )
    selected: AreaEstimate | None = None
    fresh_mapping: Mapping | None = None
    baseline: float | None = None
    known_reports: tuple[peri_scribe.incidents.IncidentUpdate, ...] = ()
    result: list[AreaEstimate] = []
    for time in sorted(times):
        if time in report_by_time:
            known_reports = (*known_reports, report_by_time[time])
        mapping = mapping_by_time.get(time)
        if mapping is not None:
            if mapping.surveyed:
                fresh_mapping = mapping
                baseline = (
                    known_reports[-1].measurements["incident_size"]
                    if known_reports
                    else None
                )
            if (
                mapping.surveyed
                or selected is None
                or selected.source is AreaSource.MAPPED
            ):
                selected = AreaEstimate(
                    time=time,
                    observation_time=mapping.time,
                    area=mapping.area,
                    source=AreaSource.MAPPED,
                    source_file=mapping.source_file,
                )
        use_report = (
            fresh_mapping is None
            or (selected is not None and selected.source is AreaSource.REPORTED)
            or report_can_take_over(
                fresh_mapping,
                known_reports,
                time,
                baseline,
                policy,
            )
        )
        if known_reports and use_report:
            report = known_reports[-1]
            selected = AreaEstimate(
                time=time,
                observation_time=report.observation_time,
                area=report.measurements["incident_size"] * units.acres,
                source=AreaSource.REPORTED,
                source_file=report.source_file,
            )
        if selected is not None:
            result.append(dataclasses.replace(selected, time=time))
    return tuple(result)


def latest_area(
    perimeters: pd.DataFrame,
    points: pd.DataFrame,
    incident_rows: pd.DataFrame | None = None,
    *,
    history: tuple[AreaEstimate, ...] | None = None,
) -> pint.Quantity[float] | None:
    """Keep current-size consumers consistent while allowing undated source fallbacks.

    The chronological selector governs when dated evidence exists. Otherwise, usable
    geometry takes precedence over the latest point's incident size and the latest
    perimeter's supplied acreage. This preserves a current size for sparse histories.

    Args:
        perimeters: The fire's perimeter rows, with the latest rows last.
        points: The fire's incident location rows, with the latest rows last.
        incident_rows: The optional independent incident history.
        history: Already selected area estimates, or None to select them.

    Returns:
        The selected area as a unit-bearing quantity, or None without usable evidence.
    """
    if history is None:
        history = area_history(perimeters, points, incident_rows)
    if history:
        return history[-1].area
    for _, row in perimeters.iloc[::-1].iterrows():
        if (area := row_area(row)) is not None:
            return area
    if not points.empty:
        value = peri_scribe.geo.parsing.numeric_value(
            points.iloc[-1].get("incident_size"),
        )
        if value is not None:
            return value * units.acres
    if not perimeters.empty:
        value = peri_scribe.geo.parsing.numeric_value(
            perimeters.iloc[-1].get("area_acres"),
        )
        if value is not None:
            return value * units.acres
    return None


def historical_area(
    perimeters: pd.DataFrame,
    points: pd.DataFrame,
    incident_rows: pd.DataFrame | None = None,
    *,
    history: tuple[AreaEstimate, ...] | None = None,
) -> pint.Quantity[float] | None:
    """Keep formerly qualifying fires visible after legitimate acreage corrections.

    Dated estimates use the same policy as current size. Without a usable chronological
    estimate, undated geometry and supplied size, discovery, or final acreage can
    establish that a sparse record reached the inclusion threshold.

    Args:
        perimeters: The fire's perimeter observations and stored measurements.
        points: Incident locations and their reported acreage fields.
        incident_rows: The optional independent reporting history.
        history: Already selected area estimates, or None to select them.

    Returns:
        The largest selected historical area, or a sparse-record fallback maximum; None
        when no usable area is available.
    """
    if history is None:
        history = area_history(perimeters, points, incident_rows)
    if history:
        return max(estimate.area for estimate in history)
    values = []
    for _, row in perimeters.iterrows():
        measured = row_area(row)
        reported = peri_scribe.geo.parsing.numeric_value(row.get("area_acres"))
        if measured is not None:
            values.append(measured)
        elif reported is not None and reported >= 0:
            values.append(reported * units.acres)
    for frame in (points, incident_rows):
        if frame is None:
            continue
        for column in ("incident_size", "discovery_acres", "final_acres"):
            for value in frame.get(column, ()):
                number = peri_scribe.geo.parsing.numeric_value(value)
                if number is not None and number >= 0:
                    values.append(number * units.acres)
    return max(values, default=None)


def presented_area(
    reported: pint.Quantity[float] | None,
    calculated: pint.Quantity[float] | None,
) -> pint.Quantity[float] | None:
    """Growth measurements describe geometry whenever it is available.

    Args:
        reported: Supplied acreage available when geometry cannot be measured.
        calculated: The geometry's area as a unit-bearing quantity, if available.

    Returns:
        The calculated measurement, falling back to the supplied acreage.
    """
    return calculated if calculated is not None else reported
