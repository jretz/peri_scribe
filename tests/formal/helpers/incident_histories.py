"""Transport whole incident histories through Lean, normalization, and real storage."""

from __future__ import annotations

import dataclasses
import datetime
import itertools
import operator
import pathlib

import numpy as np

import peri_scribe.fires.sources
import peri_scribe.geo.package
import peri_scribe.incidents
import peri_scribe.sources.feeds
import tests.helpers.factories.geometry
import tests.helpers.factories.peri_scribe.models


EPOCH = datetime.datetime(2026, 1, 1, tzinfo=datetime.UTC)
type History = tuple[peri_scribe.incidents.IncidentUpdate, ...]


def moment(value: int) -> datetime.datetime:
    """Use exact UTC seconds to match the proof's discrete reporting clock.

    Args:
        value: Seconds after the shared epoch.

    Returns:
        The corresponding timezone-aware timestamp.
    """
    return EPOCH + datetime.timedelta(seconds=value)


def cases() -> list[History]:
    """Exercise cross-field ledgers, timestamp ties, missing data, and older reports.

    Returns:
        Deterministic exhaustive short histories and longer generated sequences.
    """
    options = [
        peri_scribe.incidents.IncidentUpdate(
            observation_time=moment(time),
            report_time=None if report < 0 else moment(report),
            confirmed=confirmed,
            source="wfigs_location" if direct else "wfigs_perimeter",
            source_file=f"{file:06d}.gpkg",
            serial=serial,
            measurements={
                column: float(value)
                for column, value in zip(
                    peri_scribe.incidents.VALUE_COLUMNS,
                    values,
                    strict=True,
                )
                if value >= 0
            },
        )
        for time, report, confirmed, direct, serial, file, values in (
            (0, 0, True, False, 0, 0, (100, 0, 40, 50, 80)),
            (0, 0, False, True, 0, 1, (100, 10, -1, -1, 60)),
            (1, 0, False, True, 1, 1, (50, 5, 0, 20, 0)),
            (1, 0, False, False, 2, 0, (120, -1, 50, 60, -1)),
            (1, 1, True, True, 0, 2, (80, 20, -1, -1, 40)),
            (2, -1, False, True, 0, 1, (-1, -1, -1, 0, -1)),
            (2, 2, False, True, 2, 0, (30, 1, 0, -1, 10)),
            (3, 0, True, False, 1, 2, (90, 0, -1, 10, 0)),
            (3, -1, True, True, 1, 2, (-1, 30, -1, 5, -1)),
            (3, 3, True, True, 0, 0, (-1, -1, -1, -1, -1)),
        )
    ]
    result: list[History] = [(), *itertools.product(options, repeat=3)]
    generator = np.random.default_rng(20260926)
    for _ in range(300):
        reports = []
        for _index in range(generator.integers(4, 18)):
            template = options[int(generator.integers(len(options)))]
            reports.append(
                dataclasses.replace(
                    template,
                    observation_time=moment(int(generator.integers(8))),
                    serial=int(generator.integers(4)),
                    source_file=f"{generator.integers(4):06d}.gpkg",
                    measurements={
                        column: float(generator.choice((0, 1, 49, 50, 51, 100)))
                        for column in peri_scribe.incidents.VALUE_COLUMNS
                        if generator.choice((False, True))
                    },
                ),
            )
        result.append(tuple(reports))
    return result


def exact_integer(value: float) -> int:
    """Reject fractional drift instead of hiding it in the discrete oracle projection.

    Args:
        value: An expected integral measurement or UTC offset.

    Returns:
        The unchanged value in the oracle's integer representation.
    """
    assert value.is_integer(), value
    return int(value)


def fields(update: peri_scribe.incidents.IncidentUpdate) -> list[tuple[int, ...]]:
    """Project complete field metadata so agreement cannot hide provenance mistakes.

    Args:
        update: One supplied or reconciled update.

    Returns:
        The Lean entry vector for each present measurement.
    """
    return [
        (
            exact_integer((update.observation_time - EPOCH).total_seconds()),
            int(update.source == "wfigs_location"),
            update.serial,
            int(pathlib.Path(update.source_file).stem.split(",")[0]),
            (
                -1
                if update.report_time is None
                else exact_integer((update.report_time - EPOCH).total_seconds())
            ),
            int(update.confirmed),
            index,
            exact_integer(float(update.measurements[column])),
        )
        for index, column in enumerate(peri_scribe.incidents.VALUE_COLUMNS)
        if column in update.measurements
    ]


def command(history: History) -> str:
    """Send original unsorted evidence to the executable proof definition.

    Args:
        history: The source updates before reconciliation.

    Returns:
        A single line in the incident oracle protocol.
    """
    return "history " + " ".join(
        ",".join(map(str, vector)) for update in history for vector in fields(update)
    )


def projection(history: History) -> tuple[int, ...]:
    """Ignore simultaneous row packaging while preserving every measurement attribute.

    Args:
        history: The implementation's reconciled updates.

    Returns:
        Canonical time/field order matching the Lean oracle's result.
    """
    vectors = [vector for update in history for vector in fields(update)]
    return tuple(
        itertools.chain.from_iterable(
            sorted(vectors, key=operator.itemgetter(0, 6)),
        ),
    )


def assert_provenance(original: History, actual: History) -> None:
    """Validate full source paths beyond the oracle's numeric filename identities.

    Args:
        original: Source evidence corresponding to the oracle input.
        actual: Effective rows returned by production reconciliation.
    """
    for update in actual:
        for vector in fields(update):
            supporting = {
                (source.source, source.source_file)
                for source in original
                for candidate in fields(source)
                if candidate[:7] == vector[:7]
            }
            assert (update.source, update.source_file) in supporting, update


def source_history(
    history: History,
    directory: pathlib.Path,
) -> tuple[peri_scribe.fires.sources.ReadFireSources, History]:
    """Keep raw polygon reports independent of their identical geometry timestamps.

    Args:
        history: A generated sequence with valid source confirmation fields.
        directory: The temporary root for provenance references.

    Returns:
        Raw source rows and matching oracle updates with normalized feed provenance.
    """
    rows = []
    paths = []
    normalized = []
    for serial, update in enumerate(history):
        direct = update.source == "wfigs_location"
        feed = (
            peri_scribe.sources.feeds.WFIGS_INCIDENT_LOCATIONS_FEED
            if direct
            else peri_scribe.sources.feeds.WFIGS_PERIMETERS_FEED
        )
        prefix = "" if direct else "attr_"
        attributes: dict[str, object] = {
            prefix + key: update.measurements[column]
            for column, key in zip(
                peri_scribe.incidents.VALUE_COLUMNS,
                peri_scribe.incidents.ATTRIBUTE_KEYS,
                strict=True,
            )
            if column in update.measurements
        }
        attributes[prefix + "ICS209ReportDateTime"] = update.report_time
        attributes[prefix + "ModifiedBySystem"] = "ics209" if update.confirmed else ""
        attributes["attr_ModifiedOnDateTime_dt"] = update.observation_time
        path = directory / feed.name / "000___" / f"{serial:06d},lastEdit=1.gpkg"
        paths.append(path)
        rows.append(
            peri_scribe.geo.package.FireRowRecord(
                record=tests.helpers.factories.peri_scribe.models.fire_record(
                    "Example",
                    tests.helpers.factories.peri_scribe.models.ACTIVE,
                    {"example"},
                    geometry=tests.helpers.factories.geometry.square(0.01),
                    observed_at=update.observation_time if direct else moment(0),
                ),
                source_name=feed.name,
                object_id=1,
                attributes=attributes,
            ),
        )
        normalized.append(
            dataclasses.replace(
                update,
                serial=serial,
                source_file=str(path.relative_to(directory)),
                confirmed=update.confirmed and update.report_time is not None,
            ),
        )
    return (
        peri_scribe.fires.sources.ReadFireSources(
            rows=tuple(rows),
            paths=tuple(paths),
            memberships=(),
        ),
        tuple(normalized),
    )
