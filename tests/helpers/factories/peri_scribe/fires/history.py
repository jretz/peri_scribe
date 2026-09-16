"""Build inputs for history tests."""

from __future__ import annotations

import pathlib

import peri_scribe.fires.sources
import peri_scribe.geo.package
import tests.helpers.factories.geometry
import tests.helpers.factories.peri_scribe.models
import tests.helpers.factories.time


FIRIS_FEED_NAME = "CA_Perimeters_NIFC_FIRIS_public_view_0"


WFIGS_LOCATION_FEED_NAME = "WFIGS_Incident_Locations_Current_0"


OUTPUT_WKID = 4326


ITEM_VALUE = 7


def grouped_history_input() -> tuple[
    peri_scribe.fires.sources.FireRecordGroups,
    list[peri_scribe.geo.package.FireRowRecord],
    list[pathlib.Path],
    pathlib.Path,
]:
    """Return grouped history inputs covering perimeter and point-only fires.

    Returns:
        The record groups, the fire rows, the rows' source paths, and the source
        directory.
    """
    sources_directory = pathlib.Path("data/2026/sources")
    perimeter_path = (
        sources_directory
        / FIRIS_FEED_NAME
        / "000___"
        / "000000,lastEdit=1786929991427.gpkg"
    )
    point_path = (
        sources_directory
        / WFIGS_LOCATION_FEED_NAME
        / "000___"
        / "000000,lastEdit=1786955463975.gpkg"
    )
    perimeter_records = [
        tests.helpers.factories.peri_scribe.models.fire_record(
            name,
            tests.helpers.factories.peri_scribe.models.ACTIVE,
            identifiers=frozenset({identifier}),
            geometry=tests.helpers.factories.geometry.polygon(
                (0, 0),
                (1, 0),
                (1, 1),
                (0, 0),
            ),
            observed_at=tests.helpers.factories.time.utc(2026, 8, 16, 0, 10),
        )
        for name, identifier in (
            ("Ant", "2026-cacdd-000001"),
            ("Crab", "2026-cacdd-000003"),
        )
    ]
    point_records = [
        tests.helpers.factories.peri_scribe.models.fire_record(
            name,
            tests.helpers.factories.peri_scribe.models.ACTIVE,
            identifiers=frozenset({identifier}),
            geometry=tests.helpers.factories.geometry.point(0, 0),
        )
        for name, identifier in (
            ("Ant", "2026-cacdd-000001"),
            ("Bee", "2026-cacdd-000002"),
            ("Crab", "2026-cacdd-000003"),
        )
    ]
    rows = [
        peri_scribe.geo.package.FireRowRecord(
            record=perimeter_records[0],
            object_id=1,
            source_name=FIRIS_FEED_NAME,
            attributes={"area_acres": 100},
        ),
        peri_scribe.geo.package.FireRowRecord(
            record=point_records[0],
            object_id=1,
            source_name=WFIGS_LOCATION_FEED_NAME,
            attributes={"IncidentSize": 100},
        ),
        peri_scribe.geo.package.FireRowRecord(
            record=point_records[1],
            object_id=1,
            source_name=WFIGS_LOCATION_FEED_NAME,
            attributes={"IncidentSize": 100},
        ),
        peri_scribe.geo.package.FireRowRecord(
            record=perimeter_records[1],
            object_id=1,
            source_name=FIRIS_FEED_NAME,
            attributes={"area_acres": 100},
        ),
        peri_scribe.geo.package.FireRowRecord(
            record=point_records[2],
            object_id=1,
            source_name=WFIGS_LOCATION_FEED_NAME,
            attributes={"IncidentSize": 100},
        ),
    ]
    paths = [perimeter_path, point_path, point_path, perimeter_path, point_path]
    record_groups = peri_scribe.fires.sources.FireRecordGroups(
        records=tuple(row.record for row in rows),
        record_paths=tuple(paths),
        fires=(
            tests.helpers.factories.peri_scribe.models.fire(
                name="Ant",
                identifier="2026-cacdd-000001",
            ),
            tests.helpers.factories.peri_scribe.models.fire(
                name="Bee",
                identifier="2026-cacdd-000002",
            ),
            tests.helpers.factories.peri_scribe.models.fire(
                name="Crab",
                identifier="2026-cacdd-000003",
            ),
        ),
        groups=((0, 1), (2,), (3, 4)),
        complex_identifiers=frozenset(),
    )
    return record_groups, rows, paths, sources_directory
