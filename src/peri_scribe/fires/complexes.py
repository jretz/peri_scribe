"""Resolve current complex ownership from incident declarations and mergers."""

from __future__ import annotations

import dataclasses
import datetime
import pathlib
import typing

import structlog

import peri_scribe.geo.package
import peri_scribe.geo.parsing
import peri_scribe.models
import peri_scribe.sources.snapshots


logger = structlog.get_logger()


@dataclasses.dataclass(frozen=True, kw_only=True)
class MembershipObservation:
    """A dated assignment or explicit release, independent of polygon capture time."""

    fire_identifier: str
    complex_identifier: str | None
    complex_name: str | None
    observation_time: datetime.datetime | None = None
    snapshot_time: datetime.datetime | None = None
    serial: int = 0
    incident_location: bool = False

    @property
    def order(self) -> tuple[datetime.datetime, bool, int]:
        """Prioritize incident time, location evidence, and source snapshot order.

        Returns:
            The comparison key for declarations describing the same component fire.
        """
        return (
            self.observation_time
            or self.snapshot_time
            or peri_scribe.models.EARLIEST_DATETIME,
            self.incident_location,
            self.serial,
        )


def snapshot_clock(path: pathlib.Path) -> tuple[datetime.datetime | None, int]:
    """Retain source collection order when an incident's own timestamp is unavailable.

    Args:
        path: A source snapshot or an undated caller-supplied source path.

    Returns:
        The snapshot's UTC timestamp and serial, or an undated zero-serial fallback.
    """
    try:
        source = peri_scribe.sources.snapshots.SourceFile.from_path(path)
    except ValueError:
        return None, 0
    try:
        time = datetime.datetime.fromtimestamp(
            source.last_edit_timestamp / 1000,
            tz=datetime.UTC,
        )
    except OverflowError, OSError, ValueError:
        time = None
    return time, source.serial_number


def row_observation(
    row: peri_scribe.geo.package.FireRowRecord,
    path: pathlib.Path,
) -> MembershipObservation | None:
    """Retain explicit negative declarations without inferring release from absence.

    Args:
        row: Parsed source evidence whose full raw attributes survive cache storage.
        path: The source snapshot carrying that evidence.

    Returns:
        A complete assignment or explicit release, or None for missing relationship
        evidence. A polygon's capture date never substitutes for incident modification.
    """
    if "attr_IsCpxChild" in row.attributes:
        prefix = "attr_"
    elif "IsCpxChild" in row.attributes:
        prefix = ""
    else:
        return None
    flag = row.attributes[prefix + "IsCpxChild"]
    if (
        peri_scribe.geo.parsing.is_missing(flag)
        or (isinstance(flag, str) and not flag.strip())
        or not row.record.identifiers
    ):
        return None
    child = peri_scribe.geo.parsing.is_complex_child_from(flag)
    parent = (
        peri_scribe.geo.parsing.normalize_identifier(
            row.attributes.get(prefix + "CpxID"),
        )
        if child
        else None
    )
    name = (
        peri_scribe.geo.parsing.fire_name_from(row.attributes.get(prefix + "CpxName"))
        if child
        else None
    )
    if child and parent is None:
        return None
    snapshot_time, serial = snapshot_clock(path)
    return MembershipObservation(
        fire_identifier=min(row.record.identifiers),
        complex_identifier=parent,
        complex_name=name or parent,
        observation_time=peri_scribe.geo.parsing.observation_time_from(
            row.attributes.get(prefix + "ModifiedOnDateTime_dt"),
        ),
        snapshot_time=snapshot_time,
        serial=serial,
        incident_location=not prefix,
    )


def observations(
    rows: tuple[peri_scribe.geo.package.FireRowRecord, ...],
    paths: tuple[pathlib.Path, ...],
    memberships: tuple[peri_scribe.models.ComplexMembership, ...],
    membership_paths: tuple[pathlib.Path, ...],
) -> list[MembershipObservation]:
    """Combine dated row declarations with memberships lacking a parsed fire row.

    One snapshot can contain several dated declarations for the same relationship.

    Args:
        rows: Fire records retaining the source's relationship attributes.
        paths: Snapshot provenance aligned with the records.
        memberships: Assignments and explicit releases preserved by source parsing.
        membership_paths: Their aligned snapshot paths, or empty for an undated caller.

    Returns:
        Current-ownership evidence, including explicit releases and dated fallbacks.

    Raises:
        ValueError: A nonempty provenance tuple is not aligned with its source records.
    """
    if membership_paths and len(membership_paths) != len(memberships):
        message = "Complex memberships and source paths must have matching lengths"
        raise ValueError(message)
    result: list[MembershipObservation] = []
    covered: set[
        tuple[str, str | None, pathlib.Path | None, datetime.datetime | None]
    ] = set()
    for row, path in zip(rows, paths, strict=True):
        observation = row_observation(row, path)
        if observation is None:
            continue
        result.append(observation)
        covered.update(
            (
                identifier,
                observation.complex_identifier,
                path if membership_paths else None,
                observation.observation_time,
            )
            for identifier in row.record.identifiers
        )
    for index, membership in enumerate(memberships):
        path = membership_paths[index] if membership_paths else None
        if (
            membership.fire_identifier,
            membership.complex_identifier,
            path,
            membership.observation_time,
        ) in covered:
            continue
        snapshot_time, serial = snapshot_clock(path) if path is not None else (None, 0)
        result.append(
            MembershipObservation(
                fire_identifier=membership.fire_identifier,
                complex_identifier=membership.complex_identifier,
                complex_name=membership.complex_name,
                observation_time=membership.observation_time,
                snapshot_time=snapshot_time,
                serial=serial,
                incident_location=(
                    path is not None and "WFIGS_Incident_Locations" in str(path)
                ),
            ),
        )
    return result


def current_parent(
    fire: peri_scribe.models.Fire,
    parents: typing.Mapping[peri_scribe.models.Fire, str | None],
    ambiguous: set[peri_scribe.models.Fire],
    fires_by_identifier: typing.Mapping[str, peri_scribe.models.Fire],
) -> str | None:
    """Follow aggregate mergers while refusing ambiguous or cyclic ownership.

    Args:
        fire: The component whose ultimate current parent is requested.
        parents: Latest unambiguous direct declarations, including explicit releases.
        ambiguous: Components with contradictory declarations at the same highest rank.
        fires_by_identifier: Grouped identities indexed by every known alias.

    Returns:
        The terminal complex identifier, or None when no single current owner is known.
    """
    if fire in ambiguous:
        return None
    parent = parents.get(fire)
    visited = {fire}
    while parent is not None:
        ancestor = fires_by_identifier.get(parent)
        if ancestor is None:
            return parent
        if ancestor in visited or ancestor in ambiguous:
            return None
        visited.add(ancestor)
        next_parent = parents.get(ancestor)
        if next_parent is None:
            return parent
        parent = next_parent
    return None


def resolve(
    declarations: list[MembershipObservation],
    fires_by_identifier: dict[str, peri_scribe.models.Fire],
) -> list[peri_scribe.models.FireComplex]:
    """Keep one reciprocal current owner while retaining historical aggregate identity.

    Args:
        declarations: Dated assignments and explicit releases across source snapshots.
        fires_by_identifier: Identified grouped fires, indexed by every alias.

    Returns:
        Every declared aggregate, including aggregates emptied by a transfer or merger.
        Labels retain their first observed spelling; ownership is independent of order.

    Raises:
        ValueError: Input fires already belong to an ownership graph. Regroup fresh fire
            objects before constructing replacement ownership from changed evidence.
    """
    if any(fire.complex is not None for fire in fires_by_identifier.values()):
        message = "Complex ownership must be constructed from unassigned fire objects"
        raise ValueError(message)
    latest: dict[peri_scribe.models.Fire, tuple[datetime.datetime, bool, int]] = {}
    candidates: dict[peri_scribe.models.Fire, set[str | None]] = {}
    names: dict[str, str] = {}
    for declaration in declarations:
        fire = fires_by_identifier.get(declaration.fire_identifier)
        if fire is None:
            logger.warning(
                "Complex membership references an unidentified fire",
                fire_identifier=declaration.fire_identifier,
                complex_identifier=declaration.complex_identifier,
            )
            continue
        parent = declaration.complex_identifier
        if parent is not None:
            ancestor = fires_by_identifier.get(parent)
            parent = ancestor.identifier or parent if ancestor is not None else parent
            names.setdefault(parent, declaration.complex_name or parent)
        order = declaration.order
        previous = latest.get(fire)
        if previous is None or order > previous:
            latest[fire] = order
            candidates[fire] = {parent}
        elif order == previous:
            candidates[fire].add(parent)
    ambiguous = {fire for fire, choices in candidates.items() if len(choices) > 1}
    parents = {
        fire: next(iter(choices))
        for fire, choices in candidates.items()
        if fire not in ambiguous
    }
    members: dict[str, set[peri_scribe.models.Fire]] = {
        parent: set() for parent in names
    }
    for fire in set(fires_by_identifier.values()):
        parent = current_parent(fire, parents, ambiguous, fires_by_identifier)
        if parent is not None:
            members[parent].add(fire)
    return [
        peri_scribe.models.FireComplex(
            name=names[parent],
            identifier=parent,
            fires=frozenset(fires),
        )
        for parent, fires in members.items()
    ]
