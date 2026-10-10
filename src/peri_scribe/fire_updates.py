"""Record interesting fires with new mapping after successful KMZ generation.

Algorithm reasoning and contracts:
[History ownership](../../docs/algorithms/history-ownership.md)
[Update journal](../../docs/algorithms/update-journal.md)
"""

from __future__ import annotations

import collections
import dataclasses
import datetime
import hashlib
import itertools
import json
import pathlib
import typing
import uuid

import pydantic

import peri_scribe.fire_update_records
import peri_scribe.logging
import peri_scribe.models
import peri_scribe.perimeters.identity
import peri_scribe.presentation.fire_data
import peri_scribe.presentation.perimeters
import peri_scribe.presentation.selection
import peri_scribe.publication
import peri_scribe.report.gathering


class State(pydantic.BaseModel):
    """Remember all mapped fires, including those outside the interesting sections."""

    model_config = pydantic.ConfigDict(
        extra="forbid",
        frozen=True,
        revalidate_instances="always",
    )
    version: typing.Literal[1] = 1
    perimeters: dict[
        peri_scribe.fire_update_records.EncodedIdentity,
        frozenset[str],
    ] = pydantic.Field(default_factory=dict)
    aliases: dict[
        peri_scribe.fire_update_records.EncodedIdentity,
        peri_scribe.fire_update_records.EncodedIdentity,
    ] = pydantic.Field(default_factory=dict)
    names: dict[peri_scribe.fire_update_records.EncodedIdentity, frozenset[str]] = (
        pydantic.Field(default_factory=dict)
    )
    sources: dict[peri_scribe.fire_update_records.EncodedIdentity, frozenset[str]] = (
        pydantic.Field(default_factory=dict)
    )
    lineage: dict[
        peri_scribe.fire_update_records.EncodedIdentity,
        frozenset[peri_scribe.fire_update_records.EncodedIdentity],
    ] = pydantic.Field(default_factory=dict)
    owners: dict[
        peri_scribe.fire_update_records.EncodedIdentity,
        peri_scribe.fire_update_records.EncodedIdentity,
    ] = pydantic.Field(default_factory=dict)


@dataclasses.dataclass(frozen=True, kw_only=True)
class Ownership:
    """Separate durable evidence buckets from the fires currently inheriting them."""

    keys: dict[peri_scribe.presentation.selection.AreaKey, str]
    histories: dict[peri_scribe.presentation.selection.AreaKey, frozenset[str]]
    claims: dict[peri_scribe.presentation.selection.AreaKey, frozenset[str]]
    owners: dict[str, str]


class PendingUpdates(pydantic.BaseModel):
    """Retain a completed KMZ's append and checkpoint until both are acknowledged."""

    model_config = pydantic.ConfigDict(extra="forbid", frozen=True)
    records: peri_scribe.fire_update_records.Records
    state: State
    timestamp: pydantic.AwareDatetime
    batch_id: str = pydantic.Field(min_length=1)


@dataclasses.dataclass(frozen=True, kw_only=True)
class PreparedUpdates:
    """Freeze log entries and their mapping baseline before publishing the KMZ."""

    records: tuple[dict[str, object], ...]
    state: State


def state_path(year_directory: pathlib.Path) -> pathlib.Path:
    """Keep the mapping baseline beside other derived publication state.

    Args:
        year_directory: The year directory containing derived outputs.

    Returns:
        The fire-update checkpoint path.
    """
    return year_directory / "derived" / "fire_updates_state.json"


def read_authoritative[Document: pydantic.BaseModel](
    path: pathlib.Path,
    document_type: type[Document],
) -> Document | None:
    """Keep invalid retained intent distinct from an absent initial checkpoint.

    Args:
        path: The authoritative update checkpoint or pending journal.
        document_type: The complete schema for embedded records and identity types.

    Returns:
        A validated document, or None only when its file does not exist. Invalid or
        unreadable retained state propagates its error without writing anything.
    """
    try:
        content = path.read_bytes()
    except FileNotFoundError:
        return None
    return document_type.model_validate_json(content)


def perimeter_signature(
    perimeter: peri_scribe.presentation.perimeters.Perimeter,
) -> str:
    """Recognize a new survey or shape without treating ring order as new mapping.

    Args:
        perimeter: A non-empty mapped perimeter and its observation time.

    Returns:
        A stable digest of its normalized geometry and UTC observation time.
    """
    return peri_scribe.perimeters.identity.signature(
        perimeter.geometry,
        perimeter.observation_time,
    )


def identity_keys(
    fire: peri_scribe.presentation.fire_data.FireSummary,
) -> tuple[str, ...]:
    """Match every known identifier without conflating distinct same-named fires.

    Args:
        fire: A prepared fire with all currently known aliases.

    Returns:
        External and internal component aliases, using the name only for legacy fires
        with neither kind of identity.
    """
    keys = [
        (peri_scribe.presentation.selection.IDENTIFIER_AREA_KEY, identifier)
        for identifier in sorted(fire.identifiers)
    ]
    components = fire.component_aliases | (
        {fire.component_id} if fire.component_id is not None else set()
    )
    ordered_components = sorted(
        components,
        key=lambda value: (value != fire.component_id, value),
    )
    keys.extend(
        (peri_scribe.presentation.selection.COMPONENT_AREA_KEY, component)
        for component in ordered_components
    )
    if not keys:
        keys.append((peri_scribe.presentation.selection.NAME_AREA_KEY, fire.name))
    return tuple(json.dumps(key) for key in keys)


def stable_identity(
    fire: peri_scribe.presentation.fire_data.FireSummary,
    previous: State,
) -> str | None:
    """Prefer an existing writer key when ownership arbitration permits retaining it.

    Args:
        fire: A prepared fire with all currently known aliases.
        previous: The acknowledged mapping baseline and its identity associations.

    Returns:
        The first known external or component alias's log key, or None without a
        known preference.
    """
    if not fire.identifiers and fire.component_id is None:
        return None
    for key in identity_keys(fire):
        if key in previous.aliases:
            return previous.aliases[key]
        if key in previous.perimeters:
            return key
    return None


def historical_names(previous: State) -> dict[str, frozenset[str]]:
    """Retain names for every history even when a later namesake takes its name alias.

    Args:
        previous: The acknowledged mapping baseline, including older checkpoints.

    Returns:
        All known normalized names for each stable log identity.
    """
    names = dict(previous.names)
    for alias, key in itertools.chain(
        ((key, key) for key in previous.perimeters),
        previous.aliases.items(),
    ):
        kind, name = json.loads(alias)
        if kind == peri_scribe.presentation.selection.NAME_AREA_KEY:
            names[key] = names.get(key, frozenset()) | {
                peri_scribe.models.normalize_fire_name(name),
            }
    return names


def matching_name_identities(
    fires: typing.Mapping[
        peri_scribe.presentation.selection.AreaKey,
        peri_scribe.presentation.fire_data.FireSummary,
    ],
    previous: State,
    signatures: typing.Mapping[
        peri_scribe.presentation.selection.AreaKey,
        frozenset[str],
    ],
    sources: typing.Mapping[
        peri_scribe.presentation.selection.AreaKey,
        frozenset[str],
    ],
    reserved: set[str],
) -> dict[peri_scribe.presentation.selection.AreaKey, str]:
    """Require unambiguous mapping continuity and name matches in both directions.

    Empty histories can be adopted without mapping evidence because they contain no
    logged acreage. Already owned histories cannot be claimed by a different fire.
    Acknowledged local aliases resolve recurring ambiguity after successful publication.
    Exact source references preserve continuity when corrections replace perimeters.

    Args:
        fires: Current fires still seeking a stable identity.
        previous: The acknowledged mapping baseline.
        signatures: Current mapped observations keyed by report identity.
        sources: Current and superseded source records keyed by report identity.
        reserved: Identities owned by known identifiers or another current fire.

    Returns:
        Matches with exactly one historical candidate and one current claimant.
    """
    histories: dict[str, set[str]] = {}
    for key, names in historical_names(previous).items():
        if key not in reserved:
            for name in names:
                histories.setdefault(name, set()).add(key)
    local_aliases: dict[str, set[str]] = {}
    for alias, key in previous.aliases.items():
        kind, name = json.loads(alias)
        if (
            kind == peri_scribe.presentation.selection.NAME_AREA_KEY
            and json.loads(key)[0] == "local"
        ):
            normalized = peri_scribe.models.normalize_fire_name(name)
            local_aliases.setdefault(normalized, set()).add(key)
    candidates = {}
    for identity, fire in fires.items():
        normalized = peri_scribe.models.normalize_fire_name(fire.name)
        candidates[identity] = {
            key
            for key in histories.get(normalized, ())
            if not previous.perimeters.get(key)
            or signatures[identity] & previous.perimeters[key]
            or sources[identity] & previous.sources.get(key, frozenset())
        }
        name_key = json.dumps(
            peri_scribe.presentation.selection.fire_area_key(None, fire.name),
        )
        preferred = previous.aliases.get(name_key)
        local = candidates[identity] & local_aliases.get(normalized, set())
        if preferred is not None and preferred in local:
            local = {preferred}
        if len(local) == 1:
            candidates[identity] = local
    claimants = collections.Counter(
        key for matches in candidates.values() for key in matches
    )
    return {
        identity: key
        for identity, matches in candidates.items()
        if len(matches) == 1
        for key in matches
        if claimants[key] == 1
    }


def new_identity(
    identity: peri_scribe.presentation.selection.AreaKey,
    signatures: frozenset[str],
    reserved: set[str],
    reserved_names: set[str],
) -> str:
    """Separate namesakes without changing existing histories or inventing source IDs.

    Args:
        identity: The new fire's report identity.
        signatures: Its current mapped observations.
        reserved: Historical and current identities that must remain distinct.
        reserved_names: Historical names that require a separate namesake identity.

    Returns:
        An unused report key or a local key deterministic across retries and ordering.
    """
    key = json.dumps(identity)
    name_collision = (
        identity[0] == peri_scribe.presentation.selection.NAME_AREA_KEY
        and peri_scribe.models.normalize_fire_name(identity[1]) in reserved_names
    )
    if key not in reserved and not name_collision:
        return key
    evidence = json.dumps([identity, sorted(signatures), sorted(reserved)])
    return json.dumps(["local", hashlib.sha256(evidence.encode()).hexdigest()])


def history_lineage(previous: State) -> dict[str, frozenset[str]]:
    """Keep identifier evidence available when a correction transfers ownership.

    Args:
        previous: The saved lineage and preferred history keys.

    Returns:
        Every recorded alias association, including singleton preferred keys.
    """
    lineage = dict(previous.lineage)
    for alias, key in previous.aliases.items():
        lineage[alias] = lineage.get(alias, frozenset()) | {key}
    return lineage


def history_keys(previous: State) -> set[str]:
    """Reserve dormant histories even when they have no mapped evidence.

    Args:
        previous: The complete saved history checkpoint.

    Returns:
        Every durable bucket or group representative mentioned in the checkpoint.
    """
    return (
        set(previous.perimeters)
        | set(previous.names)
        | set(previous.sources)
        | set(previous.aliases.values())
        | set(itertools.chain.from_iterable(previous.lineage.values()))
        | set(previous.owners)
        | set(previous.owners.values())
    )


def mapping_priority(
    fire: peri_scribe.presentation.fire_data.FireSummary,
) -> tuple[bool, datetime.datetime, peri_scribe.presentation.selection.AreaKey]:
    """Resolve corrections by mapped freshness, with deterministic equal-date ties.

    Args:
        fire: A current fire with all its mapped observations.

    Returns:
        A sortable priority with undated mapping below every dated observation.
    """
    latest = max(
        (
            perimeter.observation_time
            for perimeter in fire.perimeters
            if not perimeter.geometry.is_empty
            and perimeter.observation_time is not None
        ),
        default=None,
    )
    return (
        latest is not None,
        latest or datetime.datetime.min.replace(tzinfo=datetime.UTC),
        peri_scribe.report.gathering.fire_identity(fire),
    )


def history_claims(
    fires: typing.Mapping[
        peri_scribe.presentation.selection.AreaKey,
        peri_scribe.presentation.fire_data.FireSummary,
    ],
    previous: State,
    signatures: typing.Mapping[
        peri_scribe.presentation.selection.AreaKey,
        frozenset[str],
    ],
    sources: typing.Mapping[
        peri_scribe.presentation.selection.AreaKey,
        frozenset[str],
    ],
) -> dict[peri_scribe.presentation.selection.AreaKey, frozenset[str]]:
    """Inherit all alias-linked histories while gating name-only continuity.

    External and internal component aliases retain every claimable historical route.
    Legacy name-only histories require a unique mapping or source witness for adoption.
    Stored lineage remains claimable after ownership transfers.

    Args:
        fires: Current fires keyed by their report identity.
        previous: The acknowledged mapping history and identity associations.
        signatures: Current mapped observations keyed by report identity.
        sources: Current and superseded source records keyed by report identity.

    Returns:
        Existing buckets each current fire can claim before freshness arbitration.
    """
    lineage = history_lineage(previous)
    claims = {
        identity: frozenset(
            history
            for alias in identity_keys(fire)
            for history in lineage.get(
                alias,
                frozenset({alias}) if alias in previous.perimeters else frozenset(),
            )
        )
        for identity, fire in fires.items()
        if fire.identifiers or fire.component_id is not None
    }
    claimed = set(itertools.chain.from_iterable(claims.values())) | {
        history
        for alias, histories in lineage.items()
        if json.loads(alias)[0]
        in {
            peri_scribe.presentation.selection.IDENTIFIER_AREA_KEY,
            peri_scribe.presentation.selection.COMPONENT_AREA_KEY,
        }
        for history in histories
    }
    for identified in (False, True):
        seeking = {
            identity: fire
            for identity, fire in fires.items()
            if not claims.get(identity) and bool(fire.identifiers) is identified
        }
        matches = matching_name_identities(
            seeking,
            previous,
            signatures,
            sources,
            claimed,
        )
        claims.update({identity: frozenset({key}) for identity, key in matches.items()})
        claimed.update(matches.values())
    return {identity: claims.get(identity, frozenset()) for identity in fires}


def resolved_ownership(
    fires: typing.Mapping[
        peri_scribe.presentation.selection.AreaKey,
        peri_scribe.presentation.fire_data.FireSummary,
    ],
    previous: State,
    signatures: typing.Mapping[
        peri_scribe.presentation.selection.AreaKey,
        frozenset[str],
    ],
    sources: typing.Mapping[
        peri_scribe.presentation.selection.AreaKey,
        frozenset[str],
    ],
) -> Ownership:
    """Assign every history once while retaining each claimant's path to reclaim it.

    Args:
        fires: Current fires keyed by distinct report identities.
        previous: The saved evidence, alias lineage, and current owners.
        signatures: Mapped observations keyed by current report identity.
        sources: Current and superseded source references for each fire.

    Returns:
        Unique writer keys, inherited buckets, and direct current ownership.
    """
    claims = history_claims(fires, previous, signatures, sources)
    winners = {
        history: identity
        for identity in sorted(
            fires,
            key=lambda identity: mapping_priority(fires[identity]),
        )
        for history in claims[identity]
    }
    reserved = history_keys(previous) | set(winners)
    reserved_names = {
        name for names in historical_names(previous).values() for name in names
    }
    keys = {}
    for identity in sorted(fires):
        won = {history for history, winner in winners.items() if winner == identity}
        preferred = stable_identity(fires[identity], previous)
        if won:
            keys[identity] = preferred if preferred in won else min(won)
        else:
            keys[identity] = new_identity(
                identity,
                signatures[identity],
                reserved,
                reserved_names,
            )
            reserved.add(keys[identity])
    owners = {history: previous.owners.get(history, history) for history in reserved}
    owners.update({history: keys[identity] for history, identity in winners.items()})
    owners.update({key: key for key in keys.values()})
    return Ownership(
        keys=keys,
        histories={
            identity: frozenset(
                history for history, owner in owners.items() if owner == key
            )
            for identity, key in keys.items()
        },
        claims=claims,
        owners=owners,
    )


def prepare_updates[Fire: peri_scribe.presentation.fire_data.FireSummary](
    year_directory: pathlib.Path,
    fires: list[Fire],
    scores: peri_scribe.models.FireScores,
) -> PreparedUpdates:
    """Select new mapped observations against the last completed KMZ's baseline.

    Every mapped fire advances the baseline, so merely becoming interesting does not
    create an update. Missing state starts with no acknowledged perimeters. The report
    supplies selection, deduplication, names, and locations; acreage is measured from
    the latest perimeter even when the report's current area uses incident reporting.
    Inputs require distinct report identities. Source grouping keeps identifier sets
    disjoint between current fires.

    Args:
        year_directory: The year directory containing cities and the saved baseline.
        fires: All prepared fires eligible for the KMZ.
        scores: The scores selecting the report's ranked sections.

    Returns:
        Pending log entries and state, to persist only after KMZ generation succeeds.
    """
    recover_updates(year_directory)
    previous = (
        read_authoritative(
            state_path(year_directory),
            State,
        )
        or State()
    )
    fires_by_identity = {
        peri_scribe.report.gathering.fire_identity(fire): fire for fire in fires
    }
    signatures = {
        identity: frozenset(
            perimeter_signature(perimeter)
            for perimeter in fire.perimeters
            if not perimeter.geometry.is_empty
        )
        for identity, fire in fires_by_identity.items()
    }
    sources = {
        identity: frozenset(
            reference
            for perimeter in fire.perimeters
            if not perimeter.geometry.is_empty
            for reference in perimeter.source_references
        )
        for identity, fire in fires_by_identity.items()
    }
    ownership = resolved_ownership(fires_by_identity, previous, signatures, sources)
    keys = ownership.keys
    perimeters = {keys[identity]: values for identity, values in signatures.items()}
    report = peri_scribe.report.gathering.report_from_fires(
        fires,
        scores,
        year_directory,
    )
    records: list[dict[str, object]] = []
    for entry in report.fire_details:
        identity = peri_scribe.presentation.selection.fire_area_key(
            entry.identifier,
            entry.name,
            entry.component_id,
        )
        key = keys[identity]
        fire = fires_by_identity[identity]
        inherited = frozenset(
            signature
            for history in ownership.histories[identity]
            for signature in previous.perimeters.get(history, ())
        )
        if not (perimeters[key] - inherited) or fire.perimeters[-1].geometry.is_empty:
            continue
        identity_kind, identifier = json.loads(key)
        records.append({
            "log_identity": [identity_kind, identifier],
            "identifier": (
                identifier
                if identity_kind
                == peri_scribe.presentation.selection.IDENTIFIER_AREA_KEY
                else None
            ),
            "name": entry.name,
            "location": entry.location,
            "mapped_area": peri_scribe.logging.log_value(
                fire.perimeters[-1].measured_area.to("acres"),
            ),
        })
    return PreparedUpdates(
        records=tuple(records),
        state=acknowledged_state(
            fires_by_identity,
            previous,
            ownership,
            signatures,
            sources,
        ),
    )


def acknowledged_state(
    fires: typing.Mapping[
        peri_scribe.presentation.selection.AreaKey,
        peri_scribe.presentation.fire_data.FireSummary,
    ],
    previous: State,
    ownership: Ownership,
    signatures: typing.Mapping[
        peri_scribe.presentation.selection.AreaKey,
        frozenset[str],
    ],
    sources: typing.Mapping[
        peri_scribe.presentation.selection.AreaKey,
        frozenset[str],
    ],
) -> State:
    """Retain evidence and losing claims while acknowledging one completed mapping.

    Args:
        fires: Current fires keyed by report identity.
        previous: The acknowledged history checkpoint.
        ownership: The complete current assignments and inherited histories.
        signatures: Current mapped evidence for each fire.
        sources: Source references preserved through mapping corrections.

    Returns:
        The checkpoint to publish together with the prepared update records.
    """
    ordered = sorted(fires.values(), key=mapping_priority)
    aliases = previous.aliases | {
        alias: ownership.keys[identity]
        for fire in ordered
        for identity in [peri_scribe.report.gathering.fire_identity(fire)]
        for alias in identity_keys(fire)
    }
    lineage = history_lineage(previous)
    for identity, fire in fires.items():
        inherited = ownership.claims[identity] | ownership.histories[identity]
        for alias in identity_keys(fire):
            lineage[alias] = lineage.get(alias, frozenset()) | inherited
    acknowledged = dict(previous.perimeters)
    for identity, values in signatures.items():
        key = ownership.keys[identity]
        acknowledged[key] = values | previous.perimeters.get(key, frozenset())
    acknowledged_sources = dict(previous.sources)
    for identity, values in sources.items():
        key = ownership.keys[identity]
        acknowledged_sources[key] = values | previous.sources.get(key, frozenset())
    names = historical_names(previous)
    for identity, fire in fires.items():
        key = ownership.keys[identity]
        names[key] = names.get(key, frozenset()) | {
            peri_scribe.models.normalize_fire_name(fire.name),
        }
    return State(
        perimeters=acknowledged,
        aliases=aliases,
        names=names,
        sources=acknowledged_sources,
        lineage=lineage,
        owners=ownership.owners,
    )


def pending_path(year_directory: pathlib.Path) -> pathlib.Path:
    """Keep the retry journal beside its acknowledged checkpoint.

    Args:
        year_directory: The year directory containing derived outputs.

    Returns:
        The fire-update recovery journal path.
    """
    return year_directory / "derived" / "fire_updates_pending.json"


def recover_updates(year_directory: pathlib.Path) -> None:
    """Finish a completed KMZ's interrupted publication before comparing new inputs.

    Args:
        year_directory: The year directory holding the journal, log, and checkpoint.
    """
    pending = read_authoritative(
        pending_path(year_directory),
        PendingUpdates,
    )
    read_authoritative(state_path(year_directory), State)
    if pending is None:
        return
    peri_scribe.logging.append_monthly_records(
        year_directory / "logs",
        pending.records,
        suffix="-fire-updates",
        timestamp=pending.timestamp,
        batch_id=pending.batch_id,
    )
    peri_scribe.publication.write_state(state_path(year_directory), pending.state)
    pending_path(year_directory).unlink()


def write_updates(year_directory: pathlib.Path, updates: PreparedUpdates) -> None:
    """Journal completed mapping updates so interrupted appends can be retried safely.

    An empty batch still rotates older months and acknowledges uninteresting fires.
    A journal preserves the original completion time across append or checkpoint errors.

    Args:
        year_directory: The year directory containing logs and derived state.
        updates: The batch prepared from the completed KMZ's fire inputs.
    """
    pending = PendingUpdates(
        records=updates.records,
        state=updates.state,
        timestamp=datetime.datetime.now().astimezone(),
        batch_id=str(uuid.uuid4()),
    )
    recover_updates(year_directory)
    previous = read_authoritative(state_path(year_directory), State)
    if previous == pending.state:
        peri_scribe.logging.append_monthly_records(
            year_directory / "logs",
            (),
            suffix="-fire-updates",
        )
        return
    peri_scribe.publication.write_state(pending_path(year_directory), pending)
    recover_updates(year_directory)
