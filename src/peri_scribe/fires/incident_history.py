"""Preserve incident attributes before perimeter reconciliation removes snapshots."""

from __future__ import annotations

import typing

import pandas as pd

import peri_scribe.fires.history
import peri_scribe.fires.reuse
import peri_scribe.fires.sources
import peri_scribe.incidents
import peri_scribe.perimeters.versions


if typing.TYPE_CHECKING:
    import pathlib


COLUMNS = [
    peri_scribe.fires.reuse.KEY_COLUMN,
    *peri_scribe.fires.history.IDENTITY_COLUMNS,
    "observation_time",
    "report_time",
    "report_confirmed",
    "source",
    "source_file",
    "source_serial",
    *peri_scribe.incidents.VALUE_COLUMNS,
    "geometry",
]


def incident_layer_rows(
    read: peri_scribe.fires.sources.ReadFireSources,
    groups: peri_scribe.fires.sources.FireRecordGroups,
    sources_directory: pathlib.Path,
    *,
    reused: dict[int, peri_scribe.fires.reuse.Rows] | None = None,
    derivation_keys: dict[int, str] | None = None,
) -> list[dict[str, object]]:
    """Preserve reports that perimeter reconciliation might otherwise remove.

    Incident changes remain useful even when a polygon is unchanged or superseded.
    Complex parent groups are omitted to avoid duplicating their component reports.

    Args:
        read: The original source records and their snapshot paths.
        groups: Fire identities and the source-record groups assigned to them.
        sources_directory: The base directory for source provenance references.
        reused: Validated incident rows keyed by in-memory fire identity, if available.
        derivation_keys: Fingerprints covering all source observations for each fire.

    Returns:
        Reconciled incident rows with fire identity, report timing, measurements,
        provenance, and null geometry for the independent history layer.
    """
    rows: list[dict[str, object]] = []
    for fire, group in zip(groups.fires, groups.groups, strict=True):
        if peri_scribe.fires.sources.fire_is_complex_parent(groups, group):
            continue
        if reused is not None and id(fire) in reused:
            rows.extend(reused[id(fire)])
            continue
        updates: list[peri_scribe.incidents.IncidentUpdate] = []
        for index in group:
            observation = peri_scribe.perimeters.versions.source_observation_from_row(
                read.rows[index],
                read.paths[index],
                sources_directory,
            )
            row = pd.Series({
                "source": observation.source_kind.value,
                "source_attributes": observation.attributes,
                "observation_time": observation.observation_time,
                "source_file": observation.source_file,
                "source_serial": observation.serial_number,
            })
            update = peri_scribe.incidents.update_from_row(
                row,
                perimeter=observation.source_kind
                is not peri_scribe.perimeters.versions.WFIGS_LOCATION,
            )
            if update is not None:
                updates.append(update)
        rows.extend(
            {
                peri_scribe.fires.reuse.KEY_COLUMN: (
                    "" if derivation_keys is None else derivation_keys[id(fire)]
                ),
                **peri_scribe.fires.history.identity_fields(fire, None),
                "observation_time": update.observation_time,
                "report_time": update.report_time,
                "report_confirmed": update.confirmed,
                "source": update.source,
                "source_file": update.source_file,
                "source_serial": update.serial,
                **update.measurements,
                "geometry": None,
            }
            for update in peri_scribe.incidents.reconcile_updates(updates)
        )
    return rows
