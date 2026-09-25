"""Record interesting fires with new mapping after successful KMZ generation."""

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

    model_config = pydantic.ConfigDict(extra="forbid", frozen=True)
    version: typing.Literal[1] = 1
    perimeters: dict[str, frozenset[str]] = pydantic.Field(default_factory=dict)
    aliases: dict[str, str] = pydantic.Field(default_factory=dict)
    names: dict[str, frozenset[str]] = pydantic.Field(default_factory=dict)
    sources: dict[str, frozenset[str]] = pydantic.Field(default_factory=dict)


class PendingUpdates(pydantic.BaseModel):
    """Retain a completed KMZ's append and checkpoint until both are acknowledged."""

    model_config = pydantic.ConfigDict(extra="forbid", frozen=True)
    records: tuple[dict[str, object], ...]
    state: State
    timestamp: pydantic.AwareDatetime
    batch_id: str


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
        Serialized checkpoint keys, using the name only for unidentified fires.
    """
    return tuple(
        json.dumps(
            peri_scribe.presentation.selection.fire_area_key(identifier, fire.name),
        )
        for identifier in sorted(fire.identifiers) or [None]
    )


def stable_identity(
    fire: peri_scribe.presentation.fire_data.FireSummary,
    previous: State,
) -> str | None:
    """Trust known identifiers while requiring mapping evidence for name matches.

    Args:
        fire: A prepared fire with all currently known aliases.
        previous: The acknowledged mapping baseline and its identity associations.

    Returns:
        The identifier's existing log key, or None when ownership needs resolving.
    """
    if not fire.identifiers:
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


def resolved_identities(
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
) -> dict[peri_scribe.presentation.selection.AreaKey, str]:
    """Resolve ownership before any current fire can replace another's mapping.

    Known identifiers have priority. Existing name-only fires retain uniquely matched
    histories before new identifiers can claim them. New namesakes get separate keys.

    Args:
        fires: Current fires keyed by their report identity.
        previous: The acknowledged mapping history and identity associations.
        signatures: Current mapped observations keyed by report identity.
        sources: Current and superseded source records keyed by report identity.

    Returns:
        Stable log identities for the complete set of current fires.
    """
    keys = {
        identity: key
        for identity, fire in fires.items()
        if (key := stable_identity(fire, previous)) is not None
    }
    claimed = set(keys.values()) | {
        key
        for alias, key in previous.aliases.items()
        if json.loads(alias)[0]
        == peri_scribe.presentation.selection.IDENTIFIER_AREA_KEY
    }
    for identified in (False, True):
        seeking = {
            identity: fire
            for identity, fire in fires.items()
            if identity not in keys and bool(fire.identifiers) is identified
        }
        matches = matching_name_identities(
            seeking,
            previous,
            signatures,
            sources,
            claimed,
        )
        keys.update(matches)
        claimed.update(matches.values())
    reserved = set(previous.perimeters) | set(previous.aliases.values()) | claimed
    reserved_names = {
        name for names in historical_names(previous).values() for name in names
    }
    for identity in sorted(fires):
        if identity not in keys:
            keys[identity] = new_identity(
                identity,
                signatures[identity],
                reserved,
                reserved_names,
            )
            reserved.add(keys[identity])
    return keys


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

    Args:
        year_directory: The year directory containing cities and the saved baseline.
        fires: All prepared fires eligible for the KMZ.
        scores: The scores selecting the report's ranked sections.

    Returns:
        Pending log entries and state, to persist only after KMZ generation succeeds.
    """
    recover_updates(year_directory)
    previous = (
        peri_scribe.publication.read_state(
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
    keys = resolved_identities(fires_by_identity, previous, signatures, sources)
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
        )
        key = keys[identity]
        fire = fires_by_identity[identity]
        if (
            not (perimeters[key] - previous.perimeters.get(key, frozenset()))
            or fire.perimeters[-1].geometry.is_empty
        ):
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
    aliases = previous.aliases | {
        alias: keys[identity]
        for identity, fire in fires_by_identity.items()
        for alias in identity_keys(fire)
    }
    acknowledged = dict(previous.perimeters)
    for key, values in perimeters.items():
        acknowledged[key] = values | previous.perimeters.get(key, frozenset())
    acknowledged_sources = dict(previous.sources)
    for identity, values in sources.items():
        key = keys[identity]
        acknowledged_sources[key] = values | previous.sources.get(key, frozenset())
    names = historical_names(previous)
    for identity, fire in fires_by_identity.items():
        key = keys[identity]
        names[key] = names.get(key, frozenset()) | {
            peri_scribe.models.normalize_fire_name(fire.name),
        }
    return PreparedUpdates(
        records=tuple(records),
        state=State(
            perimeters=acknowledged,
            aliases=aliases,
            names=names,
            sources=acknowledged_sources,
        ),
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
    pending = peri_scribe.publication.read_state(
        pending_path(year_directory),
        PendingUpdates,
    )
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
    recover_updates(year_directory)
    previous = peri_scribe.publication.read_state(state_path(year_directory), State)
    if previous == updates.state:
        peri_scribe.logging.append_monthly_records(
            year_directory / "logs",
            (),
            suffix="-fire-updates",
        )
        return
    pending = PendingUpdates(
        records=updates.records,
        state=updates.state,
        timestamp=datetime.datetime.now().astimezone(),
        batch_id=str(uuid.uuid4()),
    )
    peri_scribe.publication.write_state(pending_path(year_directory), pending)
    recover_updates(year_directory)
