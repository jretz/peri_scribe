"""Complete identity allocation and saved evidence follow the executable resolver."""

import dataclasses
import datetime
import itertools
import json
import pathlib
import typing

import time_machine

import peri_scribe.fire_updates
import peri_scribe.models
import peri_scribe.presentation.fire_data
import peri_scribe.presentation.selection
import peri_scribe.publication
import peri_scribe.report.gathering
import peri_scribe.updates
import tests.formal.helpers.identity
import tests.formal.helpers.oracle
import tests.helpers.factories.peri_scribe.fire_updates
from measurement_units import units


type AreaKey = peri_scribe.presentation.selection.AreaKey
type FireMap = dict[AreaKey, peri_scribe.presentation.fire_data.FireSummary]
type Evidence = dict[AreaKey, frozenset[str]]

FRESH_BASE = 1_000_000
EPOCH = datetime.datetime(2026, 8, 1, tzinfo=datetime.UTC)


@dataclasses.dataclass(kw_only=True)
class Symbols:
    """Opaque hash identities are compared through a bijection to formal tokens."""

    values: dict[tuple[str, str], int] = dataclasses.field(default_factory=dict)
    keys: dict[int, str] = dataclasses.field(default_factory=dict)

    def token(self, kind: str, value: str) -> int:
        """Keep distinct keys, names, and source evidence in disjoint namespaces.

        Args:
            kind: The semantic token category.
            value: Its raw serialized value.

        Returns:
            A stable positive natural for this comparison.
        """
        token = self.values.setdefault((kind, value), len(self.values) + 1)
        assert token < FRESH_BASE
        if kind == "key":
            self.keys[token] = value
        return token

    def sequence(self, kind: str, values: typing.Iterable[str]) -> str:
        """Serialize a set or ordered source sequence without interpreting ownership.

        Args:
            kind: The semantic token category.
            values: Raw source values in a deterministic representation order.

        Returns:
            The oracle's space-delimited naturals.
        """
        return " ".join(str(self.token(kind, value)) for value in values)


def serialized(identity: AreaKey) -> str:
    """Checkpoint key spelling follows the actual JSON interchange format.

    Args:
        identity: A raw report identity.

    Returns:
        The serialized key, before any history association.
    """
    return json.dumps(identity)


def name_key(name: str) -> str:
    """Name aliases preserve source spelling while normalized names retain continuity.

    Args:
        name: The current display name.

    Returns:
        Its raw checkpoint alias.
    """
    return serialized(("name", name))


def raw_history_names(previous: peri_scribe.fire_updates.State) -> dict[str, set[str]]:
    """Expand persisted and legacy name fields into the model's input representation.

    Args:
        previous: Raw stored checkpoint fields, including name-shaped legacy keys.

    Returns:
        Normalized names associated with each historical key, without selecting owners.
    """
    names = {key: set(values) for key, values in previous.names.items()}
    for alias, key in itertools.chain(
        ((key, key) for key in previous.perimeters),
        previous.aliases.items(),
    ):
        kind, name = json.loads(alias)
        if kind == "name":
            names.setdefault(key, set()).add(
                peri_scribe.models.normalize_fire_name(name),
            )
    return names


@dataclasses.dataclass(frozen=True, kw_only=True)
class Resolution:
    """Raw current observations and acknowledged evidence remain separate inputs."""

    fires: FireMap
    previous: peri_scribe.fire_updates.State
    signatures: Evidence
    sources: Evidence

    def command(self, symbols: Symbols) -> str:
        """Ask Lean to execute all ownership phases and final allocation together.

        Args:
            symbols: The bijection shared by this comparison's input and output.

        Returns:
            The complete resolver request, with raw aliases and all competing fires.
        """
        names = raw_history_names(self.previous)
        reserved_names = set().union(*names.values()) if names else set()
        histories = []
        for key, known_names in sorted(names.items()):
            local_names = {
                peri_scribe.models.normalize_fire_name(json.loads(alias)[1])
                for alias, owner in self.previous.aliases.items()
                if owner == key
                and json.loads(alias)[0] == "name"
                and json.loads(key)[0] == "local"
            }
            histories.append(
                "/".join((
                    str(symbols.token("key", key)),
                    symbols.sequence("name", sorted(known_names)),
                    symbols.sequence(
                        "signature",
                        sorted(self.previous.perimeters.get(key, ())),
                    ),
                    symbols.sequence(
                        "source",
                        sorted(self.previous.sources.get(key, ())),
                    ),
                    symbols.sequence("name", sorted(local_names)),
                )),
            )
        current = []
        for identity, fire in sorted(self.fires.items()):
            normalized = peri_scribe.models.normalize_fire_name(fire.name)
            preferred = self.previous.aliases.get(name_key(fire.name))
            aliases = [
                serialized(("id", identifier))
                for identifier in sorted(fire.identifiers)
            ]
            current.append(
                "/".join((
                    str(symbols.token("key", serialized(identity))),
                    str(symbols.token("name", normalized)),
                    "-1" if preferred is None else str(symbols.token("key", preferred)),
                    symbols.sequence("key", aliases),
                    str(symbols.token("key", serialized(identity))),
                    str(int(identity[0] == "name" and normalized in reserved_names)),
                    symbols.sequence("signature", sorted(self.signatures[identity])),
                    symbols.sequence("source", sorted(self.sources[identity])),
                )),
            )
        reserved_identifiers = {
            owner
            for alias, owner in self.previous.aliases.items()
            if json.loads(alias)[0] == "id"
        }
        bindings = ";".join(
            f"{symbols.token('key', alias)} {symbols.token('key', owner)}"
            for alias, owner in sorted(self.previous.aliases.items())
        )
        return "|".join((
            "resolve",
            str(FRESH_BASE),
            symbols.sequence("key", sorted(reserved_identifiers)),
            symbols.sequence("key", sorted(self.previous.perimeters)),
            symbols.sequence(
                "key",
                sorted(
                    set(self.previous.perimeters) | set(self.previous.aliases.values()),
                ),
            ),
            bindings,
            ";".join(histories),
            ";".join(current),
        ))

    def actual(self, *, reverse: bool = False) -> dict[AreaKey, str]:
        """Only this side of the comparison invokes the production ownership algorithm.

        Args:
            reverse: Whether input insertion order is reversed for determinism checks.

        Returns:
            Actual assigned keys for every current report identity.
        """
        fires = dict(reversed(tuple(self.fires.items()))) if reverse else self.fires
        return peri_scribe.fire_updates.resolved_ownership(
            fires,
            self.previous,
            self.signatures,
            self.sources,
        ).keys


def batch_cases() -> tuple[Resolution, ...]:
    """Existing continuity cases now pass through both phases and fresh allocation.

    Returns:
        Complete resolvers with varied identified/name-only claimants and known owners.
    """
    result = []
    for index, case in enumerate(tests.formal.helpers.identity.cases()):
        for variant in (index % 8, (index + 3) % 8):
            fires, previous, signatures, sources, keys = (
                tests.formal.helpers.identity.fixture(case)
            )
            aliases = previous.aliases | {
                serialized(("id", f"reserved-{owner}")): key
                for owner, key in enumerate(keys)
                if case.reserved & (1 << owner)
            }
            perimeters = dict(previous.perimeters)
            changed_fires = {}
            changed_signatures = {}
            changed_sources = {}
            for identity, original_fire in fires.items():
                fire = original_fire
                owner = int(identity[1])
                if variant & (1 << owner):
                    fire = dataclasses.replace(fire, identifiers=frozenset())
                    changed = "name", fire.name
                else:
                    changed = identity
                    if variant & 4:
                        aliases[serialized(identity)] = keys[owner]
                        fire = dataclasses.replace(
                            fire,
                            name="Renamed" if owner else fire.name,
                            identifiers=fire.identifiers | {f"extra-{owner}"},
                        )
                    elif index % 5 == 0:
                        perimeters[serialized(identity)] = signatures[identity]
                changed_fires[changed] = fire
                changed_signatures[changed] = signatures[identity]
                changed_sources[changed] = sources[identity]
            result.append(
                Resolution(
                    fires=changed_fires,
                    previous=previous.model_copy(
                        update={"aliases": aliases, "perimeters": perimeters},
                    ),
                    signatures=changed_signatures,
                    sources=changed_sources,
                ),
            )
    return tuple(result)


def assert_resolution(
    case: Resolution,
    symbols: Symbols,
    expected: tuple[int, ...],
) -> dict[AreaKey, str]:
    """Known keys bind exactly; new opaque hashes must be distinct and unreserved.

    Args:
        case: The raw resolver inputs.
        symbols: The same input token table used by the oracle.
        expected: The complete executable resolver's outputs.

    Returns:
        Actual ownership, validated against the model and deterministic retries.
    """
    actual = case.actual()
    assert actual == case.actual(reverse=True)
    assert actual == case.actual()
    assert len(set(actual.values())) == len(case.fires)
    reserved = set(case.previous.perimeters) | set(case.previous.aliases.values())
    opaque = {}
    for identity, token in zip(sorted(case.fires), expected, strict=True):
        key = actual[identity]
        if token < FRESH_BASE:
            assert key == symbols.keys[token], (case, identity, expected, actual)
        else:
            assert json.loads(key)[0] == "local"
            assert key not in reserved
            assert token not in opaque or opaque[token] == key
            opaque[token] = key
    assert len(set(opaque.values())) == len(opaque)
    return actual


def check_batches() -> None:
    """Every expected owner comes from the complete executable formal resolver."""
    cases = batch_cases()
    symbols = [Symbols() for _case in cases]
    expected = tests.formal.helpers.oracle.evaluate(
        [case.command(table) for case, table in zip(cases, symbols, strict=True)],
        executable="oracleOwnership",
    )
    for case, table, outcome in zip(cases, symbols, expected, strict=True):
        assert_resolution(case, table, outcome)


@dataclasses.dataclass(frozen=True, kw_only=True)
class Observation:
    """A known lineage can change geometry, name, or identifier independently."""

    name: str
    identifiers: tuple[str, ...]
    surveys: tuple[int, ...]
    source: int

    def actual(self) -> peri_scribe.presentation.fire_data.FireSummary:
        """Use real Type1 report selection and distinct measured perimeter evidence.

        Returns:
            An actual mapped fire ready for publication preparation.
        """
        base = tests.helpers.factories.peri_scribe.fire_updates.mapped_fire()
        return dataclasses.replace(
            base,
            name=self.name,
            identifiers=frozenset(self.identifiers),
            perimeters=tuple(
                dataclasses.replace(
                    base.perimeters[0],
                    observation_time=EPOCH + datetime.timedelta(seconds=survey),
                    area=(1000 + survey) * units.acres,
                    source_references=frozenset({f"source-{self.source}"}),
                )
                for survey in self.surveys
            ),
        )


def publications() -> tuple[tuple[tuple[Observation, ...], ...], ...]:
    """Corrections and disappearing histories create competition across publications.

    Returns:
        Three independently persisted multi-publication scenarios.
    """
    timber = Observation(name="Timber", identifiers=(), surveys=(1,), source=1)
    corrected = dataclasses.replace(timber, surveys=(2,))
    identified = dataclasses.replace(corrected, identifiers=("a",))
    renamed = dataclasses.replace(
        identified,
        name="Pine",
        identifiers=("a", "extra"),
        surveys=(3,),
    )
    namesake = dataclasses.replace(timber, surveys=(4,), source=2)
    reclaimed = dataclasses.replace(timber, name="TIMBER", identifiers=("b",))
    oak = dataclasses.replace(timber, name="Oak", identifiers=("oak",))
    ash = dataclasses.replace(namesake, name="Ash")
    new_oak = dataclasses.replace(namesake, name="Oak", source=3, surveys=(8,))
    return (
        (
            (timber,),
            (corrected,),
            (identified,),
            (renamed,),
            (),
            (dataclasses.replace(renamed, identifiers=("extra",), surveys=(1, 3)),),
            (dataclasses.replace(renamed, surveys=(5,)),),
        ),
        (
            (timber,),
            (namesake,),
            (namesake,),
            (namesake, reclaimed),
            (namesake, dataclasses.replace(reclaimed, name="River", surveys=(6,))),
            (namesake,),
            (dataclasses.replace(reclaimed, name="River", surveys=(7,)), namesake),
        ),
        (
            (oak, ash),
            (dataclasses.replace(oak, identifiers=("oak", "oak-alias"), surveys=(3,)),),
            (ash,),
            (new_oak, ash),
            (
                new_oak,
                dataclasses.replace(oak, identifiers=("oak-alias",), surveys=(9,)),
                ash,
            ),
            (ash, new_oak),
        ),
    )


def publication_input(
    fires: list[peri_scribe.presentation.fire_data.FireSummary],
    previous: peri_scribe.fire_updates.State,
) -> Resolution:
    """Geometry digests are opaque source tokens; ownership is still computed by Lean.

    Args:
        fires: Current source fires before update preparation.
        previous: The actual persisted checkpoint.

    Returns:
        The complete unresolved input representation.
    """
    by_identity = {
        peri_scribe.report.gathering.fire_identity(fire): fire for fire in fires
    }
    return Resolution(
        fires=by_identity,
        previous=previous,
        signatures={
            identity: frozenset(
                peri_scribe.fire_updates.perimeter_signature(perimeter)
                for perimeter in fire.perimeters
                if not perimeter.geometry.is_empty
            )
            for identity, fire in by_identity.items()
        },
        sources={
            identity: frozenset(
                reference
                for perimeter in fire.perimeters
                if not perimeter.geometry.is_empty
                for reference in perimeter.source_references
            )
            for identity, fire in by_identity.items()
        },
    )


def checkpoint_expectations(
    case: Resolution,
    ownership: dict[AreaKey, str],
    actual: peri_scribe.fire_updates.PreparedUpdates,
) -> None:
    """Every checkpoint field is compared with the executable acknowledgement policy.

    Args:
        case: Current and previous evidence before preparation.
        ownership: Ownership already checked against the full resolver.
        actual: Prepared checkpoint and records from production.
    """
    symbols = Symbols()
    commands = []
    fields = []
    current_names = {
        identity: frozenset({peri_scribe.models.normalize_fire_name(fire.name)})
        for identity, fire in case.fires.items()
    }
    for kind, previous, current, observed in (
        (
            "signature",
            case.previous.perimeters,
            case.signatures,
            actual.state.perimeters,
        ),
        ("source", case.previous.sources, case.sources, actual.state.sources),
        ("name", raw_history_names(case.previous), current_names, actual.state.names),
    ):
        new = {ownership[identity]: values for identity, values in current.items()}
        for owner in sorted(set(previous) | set(new)):
            commands.append(
                "|".join((
                    "acknowledge",
                    symbols.sequence(kind, sorted(previous.get(owner, ()))),
                    symbols.sequence(kind, sorted(new.get(owner, ()))),
                )),
            )
            fields.append((kind, observed.get(owner, frozenset())))
        assert set(observed) == set(previous) | set(new)
    results = tests.formal.helpers.oracle.evaluate(
        commands,
        executable="oracleOwnership",
    )
    for (kind, observed), expected in zip(fields, results, strict=True):
        assert {symbols.token(kind, value) for value in observed} == set(expected)
    new_aliases = {
        serialized(("id", identifier))
        if identifier is not None
        else name_key(fire.name): ownership[identity]
        for identity, fire in case.fires.items()
        for identifier in sorted(fire.identifiers) or [None]
    }
    queries = sorted(set(case.previous.aliases) | set(new_aliases))
    alias_command = "|".join((
        "aliases",
        ";".join(
            f"{symbols.token('key', alias)} {symbols.token('key', owner)}"
            for alias, owner in sorted(case.previous.aliases.items())
        ),
        ";".join(
            f"{symbols.token('key', alias)} {symbols.token('key', owner)}"
            for alias, owner in sorted(new_aliases.items())
        ),
        symbols.sequence("key", queries),
    ))
    expected_aliases = tests.formal.helpers.oracle.evaluate(
        [alias_command],
        executable="oracleOwnership",
    )[0]
    assert set(actual.state.aliases) == set(queries)
    assert (
        tuple(symbols.token("key", actual.state.aliases[alias]) for alias in queries)
        == expected_aliases
    )
    novel = (
        tests.formal.helpers.oracle.evaluate(
            [
                "|".join((
                    "novel",
                    symbols.sequence(
                        "signature",
                        sorted(case.previous.perimeters.get(ownership[identity], ())),
                    ),
                    symbols.sequence("signature", sorted(case.signatures[identity])),
                ))
                for identity in sorted(case.fires)
            ],
            executable="oracleOwnership",
        )
        if case.fires
        else []
    )
    expected_records = {
        ownership[identity]
        for identity, (changed,) in zip(sorted(case.fires), novel, strict=True)
        if changed
    }
    assert {
        json.dumps(record["log_identity"]) for record in actual.records
    } == expected_records


def records_signature(records: typing.Iterable[dict[str, object]]) -> frozenset[str]:
    """Report ordering is independent of the set of acknowledged source records.

    Args:
        records: Prepared records before journal metadata is added.

    Returns:
        Canonical complete record contents for input-order comparisons.
    """
    return frozenset(json.dumps(record, sort_keys=True) for record in records)


def check_publications(directory: pathlib.Path) -> None:
    """Real checkpoints and journals retain prior evidence across full publications.

    Args:
        directory: An isolated directory for all checkpoint and log files.
    """
    empty_scores = peri_scribe.models.FireScores(version="formal", fires=[])
    for scenario, rounds in enumerate(publications()):
        for reverse in (False, True):
            year = directory / f"scenario-{scenario}-{int(reverse)}"
            previous = peri_scribe.fire_updates.State()
            prior_entries: tuple[peri_scribe.updates.LogEntry, ...] = ()
            for round_index, observations in enumerate(rounds):
                fires = [observation.actual() for observation in observations]
                if reverse:
                    fires.reverse()
                case = publication_input(fires, previous)
                symbols = Symbols()
                expected = tests.formal.helpers.oracle.evaluate(
                    [case.command(symbols)],
                    executable="oracleOwnership",
                )[0]
                ownership = assert_resolution(case, symbols, expected)
                prepared = peri_scribe.fire_updates.prepare_updates(
                    year,
                    fires,
                    empty_scores,
                )
                repeated = peri_scribe.fire_updates.prepare_updates(
                    year,
                    list(reversed(fires)),
                    empty_scores,
                )
                assert repeated.state == prepared.state
                assert records_signature(repeated.records) == records_signature(
                    prepared.records,
                )
                checkpoint_expectations(case, ownership, prepared)
                with time_machine.travel(
                    EPOCH + datetime.timedelta(hours=round_index),
                    tick=False,
                ):
                    peri_scribe.fire_updates.write_updates(year, prepared)
                    entries = peri_scribe.updates.read_entries(year)
                    peri_scribe.fire_updates.write_updates(year, prepared)
                    assert peri_scribe.updates.read_entries(year) == entries
                saved = peri_scribe.publication.read_state(
                    peri_scribe.fire_updates.state_path(year),
                    peri_scribe.fire_updates.State,
                )
                assert saved == prepared.state
                assert entries[: len(prior_entries)] == prior_entries
                assert len(entries) == len(prior_entries) + len(prepared.records)
                assert {
                    json.dumps(entry.log_identity)
                    for entry in entries[len(prior_entries) :]
                } == {json.dumps(record["log_identity"]) for record in prepared.records}
                assert records_signature(
                    entry.model_dump(mode="json", exclude={"timestamp", "batch_id"})
                    for entry in entries[len(prior_entries) :]
                ) == records_signature(prepared.records)
                retry = peri_scribe.fire_updates.prepare_updates(
                    year,
                    fires,
                    empty_scores,
                )
                assert not retry.records
                assert retry.state == saved
                assert saved is not None
                previous = saved
                prior_entries = entries
