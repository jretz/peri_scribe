"""Dated complex declarations carried by real parsed source rows."""

import datetime
import pathlib

import peri_scribe.fires.sources
import peri_scribe.geo.package
import peri_scribe.models


def history(
    declarations: list[tuple[int, int | None, int]],
) -> peri_scribe.fires.sources.ReadFireSources:
    """Keep incident dates distinguishable from file order and perimeter capture time.

    Args:
        declarations: Child identity, optional parent identity, and incident day.

    Returns:
        Three known fires and their ordered source evidence.
    """
    rows = []
    paths = []
    memberships = []
    for identifier in range(3):
        rows.append(
            peri_scribe.geo.package.FireRowRecord(
                record=peri_scribe.models.FireRecord(
                    name=f"Fire {identifier}",
                    status=peri_scribe.models.FireStatus.ACTIVE,
                    identifiers=frozenset({f"fire-{identifier}"}),
                ),
                object_id=identifier,
                source_name="WFIGS_Interagency_Perimeters_Current_0",
                attributes={},
            ),
        )
        paths.append(pathlib.Path("000000,lastEdit=0.gpkg"))
    for serial, (child, parent, day) in enumerate(declarations, 1):
        time = datetime.datetime(2026, 1, day, tzinfo=datetime.UTC)
        rows.append(
            peri_scribe.geo.package.FireRowRecord(
                record=peri_scribe.models.FireRecord(
                    name=f"Fire {child}",
                    status=peri_scribe.models.FireStatus.ACTIVE,
                    identifiers=frozenset({f"fire-{child}"}),
                    observed_at=datetime.datetime(2026, 2, 1, tzinfo=datetime.UTC),
                ),
                object_id=child,
                source_name="WFIGS_Interagency_Perimeters_Current_0",
                attributes={
                    "attr_IsCpxChild": parent is not None,
                    "attr_CpxID": None if parent is None else f"fire-{parent}",
                    "attr_CpxName": None if parent is None else f"Complex {parent}",
                    "attr_ModifiedOnDateTime_dt": time.isoformat(),
                },
            ),
        )
        paths.append(pathlib.Path(f"{serial:06d},lastEdit=0.gpkg"))
        if parent is not None:
            memberships.append(
                peri_scribe.models.ComplexMembership(
                    fire_identifier=f"fire-{child}",
                    complex_identifier=f"fire-{parent}",
                    complex_name=f"Complex {parent}",
                    observation_time=time,
                ),
            )
    return peri_scribe.fires.sources.ReadFireSources(
        rows=tuple(rows),
        paths=tuple(paths),
        memberships=tuple(memberships),
    )
