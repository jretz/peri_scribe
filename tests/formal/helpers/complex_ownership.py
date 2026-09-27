"""Compare complete temporal ownership with executable Lean definitions."""

from __future__ import annotations

import contextlib
import dataclasses
import datetime
import itertools
import pathlib
import sqlite3

import numpy as np

import peri_scribe.fires.sources
import peri_scribe.geo.database
import peri_scribe.geo.package
import peri_scribe.geo.reading
import peri_scribe.models
import peri_scribe.sources.feeds
import peri_scribe.sources.snapshots
import spatial_data.geometry_pool


EPOCH = datetime.datetime(2026, 1, 1, tzinfo=datetime.UTC)
ALIASES = (0, 1, 2, 0, 1, 2, None, None)
FIRE_COUNT = 3
UNOBSERVED = -2


@dataclasses.dataclass(frozen=True, kw_only=True)
class Evidence:
    """Raw incident declarations retain their clocks independently of geometry."""

    child: int
    parent: int | None
    time: int | None = 0
    snapshot: int | None = 0
    location: bool = False
    serial: int = 0
    present: bool = True
    named: bool = True
    parseable: bool = True


type History = tuple[Evidence, ...]


def moment(value: int) -> datetime.datetime:
    """Encode discrete oracle clock ticks as exact UTC seconds.

    Args:
        value: Seconds after the shared epoch.

    Returns:
        The timestamp for raw incident attributes and snapshot filenames.
    """
    return EPOCH + datetime.timedelta(seconds=value)


def command(history: History) -> str:
    """Transport unsorted declarations directly to the proved temporal definitions.

    Args:
        history: Original evidence, including intentionally absent declarations.

    Returns:
        One oracle request; zero time represents the undated earliest fallback.
    """
    entries = []
    for evidence in history:
        if not evidence.present:
            continue
        time = evidence.time if evidence.time is not None else evidence.snapshot
        entries.append(
            ",".join(
                map(
                    str,
                    (
                        evidence.child,
                        "n" if evidence.parent is None else evidence.parent,
                        0 if time is None else time + 1,
                        int(evidence.location),
                        evidence.serial if evidence.snapshot is not None else 0,
                    ),
                ),
            ),
        )
    aliases = " ".join("n" if alias is None else str(alias) for alias in ALIASES)
    return f"resolve {FIRE_COUNT} | {aliases} | {' '.join(entries)}"


def cases() -> list[History]:
    """Exercise transfers, mergers, cycles, releases, aliases, and ranking boundaries.

    Returns:
        All short histories over representative observations plus longer seeded cases.
    """
    options = [
        Evidence(child=0, parent=1),
        Evidence(child=3, parent=4),
        Evidence(child=0, parent=2, time=1),
        Evidence(child=1, parent=2, time=1),
        Evidence(child=2, parent=1, time=2),
        Evidence(child=0, parent=None, time=2),
        Evidence(child=0, parent=2, location=True),
        Evidence(child=0, parent=2, serial=1),
        Evidence(child=0, parent=6),
        Evidence(child=7, parent=1),
        Evidence(child=0, parent=None, time=2, present=False),
        Evidence(child=0, parent=2, time=None, snapshot=3, named=False),
    ]
    result: list[History] = [(), *itertools.product(options, repeat=3)]
    generator = np.random.default_rng(20260927)
    result.extend(
        tuple(
            Evidence(
                child=int(generator.integers(len(ALIASES))),
                parent=None
                if generator.integers(4) == 0
                else int(generator.integers(7)),
                time=None if generator.integers(3) == 0 else int(generator.integers(5)),
                snapshot=int(generator.integers(5)),
                serial=int(generator.integers(3)),
                location=bool(generator.integers(2)),
                present=bool(generator.integers(5)),
                named=bool(generator.integers(2)),
            )
            for _ in range(int(generator.integers(4, 16)))
        )
        for _ in range(250)
    )
    result.extend([
        (Evidence(child=0, parent=1, time=None, snapshot=None),),
        (Evidence(child=0, parent=1), Evidence(child=1, parent=None, time=1)),
    ])
    result.extend(
        tuple(
            Evidence(child=child, parent=None if parent == -1 else parent)
            for child, parent in enumerate(parents)
            if parent != UNOBSERVED
        )
        for parents in itertools.product(
            (UNOBSERVED, -1, 0, 1, 2, 6),
            repeat=FIRE_COUNT,
        )
    )
    return result


def source_history(
    history: History,
    *,
    standalone: bool = False,
) -> peri_scribe.fires.sources.ReadFireSources:
    """Carry both relationship attributes and independently parsed declarations.

    Args:
        history: Supplied evidence before temporal ownership is resolved.
        standalone: Relationship rows do not independently produce fire records.

    Returns:
        Three known fires, their aliases, raw rows, and independent snapshot provenance.
    """
    rows = []
    paths = []
    memberships = []
    membership_paths = []
    for identifier in range(FIRE_COUNT):
        rows.append(
            peri_scribe.geo.package.FireRowRecord(
                record=peri_scribe.models.FireRecord(
                    name=f"Fire {identifier}",
                    status=peri_scribe.models.FireStatus.ACTIVE,
                    identifiers=frozenset(
                        f"identifier-{alias}"
                        for alias, fire in enumerate(ALIASES)
                        if fire == identifier
                    ),
                ),
                object_id=identifier,
                source_name=peri_scribe.sources.feeds.WFIGS_PERIMETERS_FEED.name,
                attributes={},
            ),
        )
        paths.append(pathlib.Path("base.gpkg"))
    for index, evidence in enumerate(history):
        feed = (
            peri_scribe.sources.feeds.WFIGS_INCIDENT_LOCATIONS_FEED
            if evidence.location
            else peri_scribe.sources.feeds.WFIGS_PERIMETERS_FEED
        )
        filename = (
            f"{evidence.serial:06d},lastEdit="
            f"{int(moment(evidence.snapshot).timestamp()) * 1000}.gpkg"
            if evidence.snapshot is not None
            else "undated.gpkg"
        )
        path = pathlib.Path(feed.name) / "000___" / filename
        parent = None if evidence.parent is None else f"identifier-{evidence.parent}"
        name = f"Complex {evidence.parent}" if evidence.named else None
        if evidence.present:
            memberships.append(
                peri_scribe.models.ComplexMembership(
                    fire_identifier=f"identifier-{evidence.child}",
                    complex_identifier=parent,
                    complex_name=name,
                    observation_time=(
                        None if evidence.time is None else moment(evidence.time)
                    ),
                ),
            )
            membership_paths.append(path)
        identifier = ALIASES[evidence.child]
        if identifier is None or standalone or not evidence.parseable:
            continue
        prefix = "" if evidence.location else "attr_"
        attributes: dict[str, object] = {}
        if evidence.present:
            attributes = {
                prefix + "IsCpxChild": evidence.parent is not None,
                prefix + "CpxID": parent,
                prefix + "CpxName": name,
            }
            if evidence.time is not None:
                attributes[prefix + "ModifiedOnDateTime_dt"] = moment(
                    evidence.time,
                ).isoformat()
        rows.append(
            peri_scribe.geo.package.FireRowRecord(
                record=peri_scribe.models.FireRecord(
                    name=f"Fire {identifier}",
                    status=peri_scribe.models.FireStatus.ACTIVE,
                    identifiers=frozenset({f"identifier-{evidence.child}"}),
                    observed_at=moment(100),
                ),
                source_name=feed.name,
                object_id=index + FIRE_COUNT,
                attributes=attributes,
            ),
        )
        paths.append(path)
    return peri_scribe.fires.sources.ReadFireSources(
        rows=tuple(rows),
        paths=tuple(paths),
        memberships=tuple(memberships),
        membership_paths=tuple(membership_paths),
    )


def mixed_histories() -> list[History]:
    """Repeated relationships need their own clocks even within one source snapshot.

    Returns:
        Assignments and releases corrected by standalone declarations, across both
        feeds and explicit incident dates or snapshot-clock fallback.
    """
    return [
        (
            Evidence(child=0, parent=parent, snapshot=3, location=location),
            Evidence(child=0, parent=2, time=1, snapshot=3, location=location),
            Evidence(
                child=0,
                parent=parent,
                time=time,
                snapshot=3,
                location=location,
                parseable=False,
            ),
        )
        for parent in (1, None)
        for location in (False, True)
        for time in (2, None)
    ]


def parent_number(identifier: str) -> int:
    """Project canonical names without implementing any ownership decisions.

    Args:
        identifier: A production canonical or external parent identifier.

    Returns:
        The oracle's tagged parent identity.
    """
    alias = int(identifier.removeprefix("identifier-"))
    fire = ALIASES[alias]
    return alias * 2 + 1 if fire is None else fire * 2


def projection(groups: peri_scribe.fires.sources.FireRecordGroups) -> tuple[int, ...]:
    """Check reverse links, complete member sets, and actual aggregate exclusion.

    Args:
        groups: A complete production ownership graph built from raw source evidence.

    Returns:
        The same owner, surviving-component, and historical-parent vectors as Lean.
    """
    fires = {}
    for fire in groups.fires:
        assert fire.identifier is not None
        fires[int(fire.identifier.removeprefix("identifier-"))] = fire
    owners = []
    for index in range(FIRE_COUNT):
        complex_ = fires[index].complex
        owners.append(-1 if complex_ is None else parent_number(complex_.identifier))
    visible = []
    for source in peri_scribe.fires.sources.fire_sources_from_groups(groups):
        assert source.fire.identifier is not None
        visible.append(int(source.fire.identifier.removeprefix("identifier-")))
    visible.sort()
    parents = sorted(parent_number(parent) for parent in groups.complex_identifiers)
    forward = []
    for parent in parents:
        members = [index for index, owner in enumerate(owners) if owner == parent]
        for index in members:
            complex_ = fires[index].complex
            assert complex_ is not None
            assert complex_.fires == frozenset(fires[member] for member in members)
            assert all(member.complex is complex_ for member in complex_.fires)
        forward.extend([parent, len(members), *members])
    return (*owners, len(visible), *visible, len(parents), *forward)


def cached_history(
    history: History,
    path: pathlib.Path,
    *,
    standalone: bool = False,
) -> peri_scribe.fires.sources.ReadFireSources:
    """Round-trip raw relationship evidence through the actual parsed-cache schema.

    Args:
        history: Original evidence whose timestamps and negative declarations matter.
        path: Per-case temporary SQLite database.
        standalone: Preserve declarations lacking independently parseable fire records.

    Returns:
        Rehydrated rows and memberships retaining independently supplied source paths.
    """
    read = source_history(history, standalone=standalone)
    with contextlib.closing(sqlite3.connect(path)) as connection:
        peri_scribe.geo.database.reset_database(connection)
        peri_scribe.geo.database.write_snapshot(
            connection,
            peri_scribe.sources.snapshots.SourceFile(
                serial_number=1,
                last_edit_timestamp=1,
            ),
            size=1,
            mtime_ns=1,
            contents=peri_scribe.geo.package.GeopackageContents(
                rows=read.rows,
                memberships=read.memberships,
            ),
            checksum="complex-history",
        )
        connection.commit()
        contents = peri_scribe.geo.reading.fetch_snapshot_rows(
            connection,
            1,
            checksum="complex-history",
            geometry_pool=spatial_data.geometry_pool.GeometryPool(),
        )
        assert contents is not None
        assert contents.rows == read.rows
        assert contents.memberships == read.memberships
        return dataclasses.replace(
            read,
            rows=contents.rows,
            memberships=contents.memberships,
        )
