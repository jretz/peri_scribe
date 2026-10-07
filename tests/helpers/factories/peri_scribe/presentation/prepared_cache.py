"""Build precise evidence and extensible records for persistent-cache checks."""

from __future__ import annotations

import dataclasses
import datetime
import typing

import pandas as pd

import peri_scribe.areas
import peri_scribe.incidents


if typing.TYPE_CHECKING:
    import pint


@dataclasses.dataclass(frozen=True, kw_only=True)
class NestedEvidence:
    """Allow future nested record fields to exercise the serialization boundary."""

    values: object


@dataclasses.dataclass(frozen=True, kw_only=True)
class ExtendedHistory(peri_scribe.areas.PreparedHistory):
    """Ensure subclass fields cannot silently disappear from a cache payload."""

    evidence: NestedEvidence


def extended() -> ExtendedHistory:
    """Exercise added fields without depending on the current domain field inventory.

    Returns:
        An extended record with ordered mapping keys, sequences, nulls, and records.
    """
    return ExtendedHistory(
        updates=(),
        estimates=(),
        latest_area=None,
        historical_area=None,
        evidence=NestedEvidence(
            values={
                ("second", 2): [None, pd.NA, pd.NaT],
                ("first", 1): (NestedEvidence(values=-0.0),),
            },
        ),
    )


def history(
    *,
    time: datetime.datetime,
    area: pint.Quantity[float] | None,
    measurements: dict[str, float],
) -> peri_scribe.areas.PreparedHistory:
    """Combine source units, optional reports, and ordered measurement fields.

    Args:
        time: The exact observed instant and its storage representation.
        area: A measurement in its original unit, or absent area evidence.
        measurements: Incident measurements in deliberate insertion order.

    Returns:
        Prepared evidence suitable for exact representation checks.
    """
    return peri_scribe.areas.PreparedHistory(
        updates=(
            peri_scribe.incidents.IncidentUpdate(
                observation_time=time,
                report_time=None,
                confirmed=False,
                source="source 🔥",
                source_file="snapshot.gpkg",
                serial=7,
                measurements=measurements,
            ),
        ),
        estimates=()
        if area is None
        else (
            peri_scribe.areas.AreaEstimate(
                time=time,
                observation_time=time,
                area=area,
                source=peri_scribe.areas.AreaSource.REPORTED,
                source_file="snapshot.gpkg",
            ),
        ),
        latest_area=area,
        historical_area=area,
    )
