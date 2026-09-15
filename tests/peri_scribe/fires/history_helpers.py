"""Provide data builders and stand-ins for history tests."""

from __future__ import annotations

import pathlib
import typing

import peri_scribe.fires.sources
import peri_scribe.geo.package
import peri_scribe.models
import tests.factories


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
        tests.factories.fire_record(
            name,
            tests.factories.ACTIVE,
            identifiers=frozenset({identifier}),
            geometry=tests.factories.polygon((0, 0), (1, 0), (1, 1), (0, 0)),
            observed_at=tests.factories.utc(2026, 8, 16, 0, 10),
        )
        for name, identifier in (
            ("Ant", "2026-cacdd-000001"),
            ("Crab", "2026-cacdd-000003"),
        )
    ]
    point_records = [
        tests.factories.fire_record(
            name,
            tests.factories.ACTIVE,
            identifiers=frozenset({identifier}),
            geometry=tests.factories.point(0, 0),
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
            tests.factories.fire(name="Ant", identifier="2026-cacdd-000001"),
            tests.factories.fire(name="Bee", identifier="2026-cacdd-000002"),
            tests.factories.fire(name="Crab", identifier="2026-cacdd-000003"),
        ),
        groups=((0, 1), (2,), (3, 4)),
        complex_identifiers=frozenset(),
    )
    return record_groups, rows, paths, sources_directory


def make_failing_history_reader(
    *,
    real_history_rows_for_fire: typing.Callable[
        ...,
        tuple[list[dict[str, object]], list[dict[str, object]]],
    ],
) -> typing.Callable[..., tuple[list[dict[str, object]], list[dict[str, object]]]]:
    """Create a callback with controlled dependencies.

    Fail one fire's history computation to exercise worker error propagation.

    Args:
        real_history_rows_for_fire: Original history reader used for nonfailing fires.

    Returns:
        The callback bound to the supplied dependencies.
    """

    def failing_history_rows_for_fire(
        fire: peri_scribe.models.Fire,
        group: tuple[int, ...],
        full_rows: list[peri_scribe.geo.package.FireRowRecord],
        full_paths: list[pathlib.Path],
        *,
        sources_directory: pathlib.Path,
        classification: peri_scribe.models.FireClassification | None,
    ) -> tuple[list[dict[str, object]], list[dict[str, object]]]:
        """Fail one fire's history computation to exercise worker error propagation.

        Args:
            fire: Fire whose observations are being grouped or derived.
            group: Indices selecting this fire's rows from the complete input.
            full_rows: All source rows available to the history computation.
            full_paths: Source paths aligned with the complete row collection.
            sources_directory: Root directory used to resolve source provenance.
            classification: Optional border classification attached to the derived
                history.

        Returns:
            The real perimeter and point rows for fires outside the failing case.

        Raises:
            RuntimeError: If the selected fire is the configured failure case.
        """
        if fire.identifier == "2026-cacdd-000003":
            message = "perimeter failure"
            raise RuntimeError(message)
        return real_history_rows_for_fire(
            fire,
            group,
            full_rows,
            full_paths,
            sources_directory=sources_directory,
            classification=classification,
        )

    return failing_history_rows_for_fire
