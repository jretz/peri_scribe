"""Connect checked history transfer to raw aliases and real publication artifacts."""

from __future__ import annotations

import dataclasses
import datetime
import itertools
import json
import pathlib
import typing

import shapely
import time_machine

import peri_scribe.fire_updates
import peri_scribe.models
import peri_scribe.paths
import peri_scribe.presentation.fire_data
import peri_scribe.presentation.selection
import peri_scribe.publication
import peri_scribe.updates
import tests.formal.helpers.identity_lifecycle
import tests.formal.helpers.oracle
import tests.helpers.factories.peri_scribe.fire_updates_ownership
from measurement_units import units


type AreaKey = peri_scribe.presentation.selection.AreaKey
type Resolution = tests.formal.helpers.identity_lifecycle.Resolution
EPOCH = tests.formal.helpers.identity_lifecycle.EPOCH


def key(value: str) -> str:
    """Use the checkpoint's real serialized identifier namespace.

    Args:
        value: An external identifier or fixture history identifier.

    Returns:
        Its serialized checkpoint key.
    """
    return json.dumps(("id", value))


def history_keys(previous: peri_scribe.fire_updates.State) -> set[str]:
    """Raw checkpoint references identify durable buckets even without perimeter rows.

    Args:
        previous: The raw acknowledged state.

    Returns:
        Every existing bucket or stored representative, without resolving ownership.
    """
    return set().union(
        previous.perimeters,
        previous.names,
        previous.sources,
        previous.aliases.values(),
        previous.owners,
        previous.owners.values(),
        *previous.lineage.values(),
    )


def lineage(previous: peri_scribe.fire_updates.State) -> dict[str, frozenset[str]]:
    """Legacy alias bindings contribute raw lineage evidence alongside saved sets.

    Args:
        previous: Serialized state before the current publication.

    Returns:
        Persisted alias/history relationships without selecting a current claimant.
    """
    result = dict(previous.lineage)
    for alias, history in previous.aliases.items():
        result[alias] = result.get(alias, frozenset()) | {history}
    return result


@dataclasses.dataclass(kw_only=True)
class Reference:
    """Claimants, durable buckets, and evidence have independent symbolic meanings."""

    case: Resolution
    tokens: dict[str, int] = dataclasses.field(default_factory=dict)

    def __post_init__(self) -> None:
        """Historical token order matches lexical bucket order for minimum selection."""
        for history in sorted(history_keys(self.case.previous)):
            self.token(history)

    def token(self, value: str) -> int:
        """Give each distinct serialized bucket or alias one stable symbolic token.

        Args:
            value: The complete serialized key.

        Returns:
            A positive natural retaining exact identity equality.
        """
        return self.tokens.setdefault(value, len(self.tokens) + 1)

    def sequence(self, values: typing.Iterable[str], *, empty: str = "") -> str:
        """Token spelling encodes input identity without implementing claim selection.

        Args:
            values: Raw keys in their declared representation order.
            empty: Protocol spelling for the empty sequence.

        Returns:
            Space-delimited symbolic keys.
        """
        return " ".join(str(self.token(value)) for value in values) or empty

    @property
    def identities(self) -> tuple[AreaKey, ...]:
        """Claimant ranks preserve canonical report-key ordering for equal timestamps.

        Returns:
            All current report identities in lexical order.
        """
        return tuple(sorted(self.case.fires))

    def aliases(self, identity: AreaKey) -> tuple[str, ...]:
        """Read external and component claims; name adoption has its separate oracle.

        Args:
            identity: One current report identity.

        Returns:
            Its complete raw external and internal component aliases.
        """
        fire = self.case.fires[identity]
        assert fire.identifiers or fire.component_id is not None
        components = set(fire.component_aliases)
        if fire.component_id is not None:
            components.add(fire.component_id)
        return (
            *(key(identifier) for identifier in sorted(fire.identifiers)),
            *(
                json.dumps(("component", value))
                for value in sorted(
                    components,
                    key=lambda value: (value != fire.component_id, value),
                )
            ),
        )

    def mapped_time(self, identity: AreaKey) -> datetime.datetime | None:
        """A timestamp belongs to a claim only when its geometry supplies mapping.

        Args:
            identity: The current claimant.

        Returns:
            Its latest nonmissing mapped time, independently of tuple position.
        """
        return max(
            (
                perimeter.observation_time
                for perimeter in self.case.fires[identity].perimeters
                if not perimeter.geometry.is_empty
                and perimeter.observation_time is not None
            ),
            default=None,
        )

    def lineage_text(self) -> str:
        """Preserve raw legacy and current associations as oracle inputs.

        Returns:
            Alias records whose history sets remain unresolved.
        """
        return " ".join(
            f"{self.token(alias)},"
            + (":".join(str(self.token(item)) for item in sorted(histories)) or "n")
            for alias, histories in sorted(lineage(self.case.previous).items())
        )

    def fire_text(self, selected: tuple[AreaKey, ...] | None = None) -> str:
        """The oracle receives raw aliases and relative dated ranks, including zero.

        Args:
            selected: A restricted claimant set for independent claim-set queries.

        Returns:
            Claimants with lexical identity rank, optional time, and raw aliases.
        """
        dated = sorted({
            time
            for identity in self.identities
            if (time := self.mapped_time(identity)) is not None
        })
        inherited = lineage(self.case.previous)
        records = []
        for identity in self.identities if selected is None else selected:
            aliases = self.aliases(identity)
            direct = [
                alias
                for alias in aliases
                if alias not in inherited and alias in self.case.previous.perimeters
            ]
            observed = self.mapped_time(identity)
            records.append(
                ",".join((
                    str(self.identities.index(identity) + 1),
                    "n" if observed is None else str(dated.index(observed)),
                    ":".join(str(self.token(alias)) for alias in aliases) or "n",
                    ":".join(str(self.token(item)) for item in direct) or "n",
                )),
            )
        return " ".join(records)

    def claim_command(self, selected: tuple[AreaKey, ...] | None = None) -> str:
        """Lean computes both individual claim sets and whole-publication competition.

        Args:
            selected: Optional claimant subset; omission includes all current fires.

        Returns:
            One executable claim-selection query over every retained history bucket.
        """
        return "|".join((
            "claim",
            self.sequence(sorted(history_keys(self.case.previous))),
            self.lineage_text(),
            self.fire_text(selected),
        ))

    def preferred(self, identity: AreaKey) -> str | None:
        """Writer preference retains the raw first existing identifier association.

        Args:
            identity: The current fire requesting a writer bucket.

        Returns:
            Its legacy alias or direct-key preference, before checking whether it won.
        """
        for alias in self.aliases(identity):
            if alias in self.case.previous.aliases:
                return self.case.previous.aliases[alias]
            if alias in self.case.previous.perimeters:
                return alias
        return None

    def owner_text(self, owners: typing.Mapping[str, str]) -> str:
        """Serialize one-hop projection without chasing representative keys.

        Args:
            owners: Raw bucket-to-writer associations.

        Returns:
            The ownership input format used by the checked definitions.
        """
        return " ".join(
            f"{self.token(history)},{self.token(owner)}"
            for history, owner in sorted(owners.items())
        )


def claims(
    references: tuple[Reference, ...],
) -> tuple[tuple[dict[AreaKey, frozenset[str]], dict[AreaKey, frozenset[str]]], ...]:
    """One batched oracle call computes all raw and winning claim sets.

    Args:
        references: Complete unresolved checkpoint/current-fire inputs.

    Returns:
        Original claims and won histories for each input case.
    """
    commands = [
        reference.claim_command(selected)
        for reference in references
        for selected in (None, *((identity,) for identity in reference.identities))
    ]
    answers = iter(
        tests.formal.helpers.oracle.evaluate(
            commands,
            executable="oracleIdentityTransfer",
        ),
    )
    results = []
    for reference in references:
        buckets = sorted(history_keys(reference.case.previous))
        winners = next(answers)
        won = {
            identity: frozenset(
                bucket
                for bucket, claimant in zip(buckets, winners, strict=True)
                if claimant == index
            )
            for index, identity in enumerate(reference.identities, 1)
        }
        original = {
            identity: frozenset(
                bucket
                for bucket, claimant in zip(buckets, next(answers), strict=True)
                if claimant == index
            )
            for index, identity in enumerate(reference.identities, 1)
        }
        results.append((original, won))
    return tuple(results)


def choose_commands(
    reference: Reference,
    won: dict[AreaKey, frozenset[str]],
) -> list[str]:
    """The proved preference/minimum selector determines existing writer choices.

    Args:
        reference: Raw checkpoint and claimant tokens.
        won: Each claimant's oracle-selected history set.

    Returns:
        One writer-selection command per current fire.
    """
    return [
        "|".join((
            "chooseWriter",
            "n"
            if (preferred := reference.preferred(identity)) is None
            else str(reference.token(preferred)),
            reference.sequence(sorted(won[identity])),
        ))
        for identity in reference.identities
    ]


def ownership(
    reference: Reference,
    expected: tuple[dict[AreaKey, frozenset[str]], dict[AreaKey, frozenset[str]]],
) -> peri_scribe.fire_updates.Ownership:
    """Actual writer keys must satisfy checked selection and independent freshness.

    Args:
        reference: The complete unresolved input.
        expected: Oracle-derived original claims and winning history sets.

    Returns:
        Production ownership after every raw claim and writer decision is checked.
    """
    case = reference.case
    actual = peri_scribe.fire_updates.resolved_ownership(
        case.fires,
        case.previous,
        case.signatures,
        case.sources,
    )
    reversed_result = peri_scribe.fire_updates.resolved_ownership(
        dict(reversed(tuple(case.fires.items()))),
        case.previous,
        case.signatures,
        case.sources,
    )
    assert actual == reversed_result
    assert actual.claims == expected[0]
    assert len(set(actual.keys.values())) == len(case.fires)
    choices = (
        tests.formal.helpers.oracle.evaluate(
            choose_commands(reference, expected[1]),
            executable="oracleIdentityTransfer",
        )
        if case.fires
        else []
    )
    reserved = history_keys(case.previous)
    for identity, (selected,) in zip(reference.identities, choices, strict=True):
        writer = actual.keys[identity]
        if selected >= 0:
            assert reference.token(writer) == selected
        else:
            assert writer not in reserved, (
                "history without winning claim",
                identity,
                writer,
            )
            requested = json.dumps(identity)
            if requested not in reserved:
                assert writer == requested
            else:
                assert json.loads(writer)[0] == "local"
        reserved.add(writer)
    return actual


def transfer_command(
    reference: Reference,
    actual: peri_scribe.fire_updates.Ownership,
) -> str:
    """Fresh allocated buckets are born self-owned before checked claim transfer.

    Args:
        reference: Raw historical and claimant inputs.
        actual: Independently validated writer allocation.

    Returns:
        The full publication ownership projection query.
    """
    buckets = history_keys(reference.case.previous) | set(actual.keys.values())
    previous = {
        bucket: reference.case.previous.owners.get(bucket, bucket) for bucket in buckets
    }
    return "|".join((
        "transfer",
        reference.sequence(sorted(buckets)),
        reference.owner_text(previous),
        reference.lineage_text(),
        reference.fire_text(),
        " ".join(
            f"{index},{reference.token(actual.keys[identity])}"
            for index, identity in enumerate(reference.identities, 1)
        ),
    ))


def assert_owners(
    reference: Reference,
    actual: peri_scribe.fire_updates.Ownership,
    result: tuple[int, ...],
) -> None:
    """Owned baselines include retained unclaimed buckets with the same representative.

    Args:
        reference: Original unresolved checkpoint and current input.
        actual: Production's complete ownership result.
        result: Oracle result for every historical and freshly allocated bucket.
    """
    buckets = sorted(history_keys(reference.case.previous) | set(actual.keys.values()))
    decoded = {token: key for key, token in reference.tokens.items()}
    expected = {
        bucket: decoded[owner] for bucket, owner in zip(buckets, result, strict=True)
    }
    assert actual.owners == expected
    assert actual.histories == {
        identity: frozenset(
            bucket for bucket, owner in expected.items() if owner == writer
        )
        for identity, writer in actual.keys.items()
    }


def observation(
    identifiers: tuple[str, ...],
    surveys: tuple[int | None, ...],
    *,
    name: str = "Timber",
) -> peri_scribe.presentation.fire_data.FireSummary:
    """Real map observations make missing dates and historical corrections explicit.

    Args:
        identifiers: Every current alias for this fire.
        surveys: Distinct survey tokens, with None retaining an undated observation.
        name: Current report name.

    Returns:
        An actual Type 1 fire admitted by the production report selector.
    """
    base = tests.formal.helpers.identity_lifecycle.Observation(
        name=name,
        identifiers=identifiers,
        surveys=(1,),
        source=1,
    ).actual()
    return dataclasses.replace(
        base,
        perimeters=tuple(
            dataclasses.replace(
                base.perimeters[0],
                observation_time=None
                if survey is None
                else (
                    datetime.datetime(1970, 1, 1, tzinfo=datetime.UTC)
                    + datetime.timedelta(seconds=survey)
                ),
                area=(1000 + (survey or 0)) * units.acres,
                source_references=frozenset({f"source-{survey}"}),
            )
            for survey in surveys
        ),
    )


def batch_cases() -> tuple[Resolution, ...]:
    """Competing aliases vary lineage, preference, recency, and retained ownership.

    Returns:
        Bounded identified-fire cases independent of production claim helpers.
    """
    result = []
    groups = ((("a",), ("b",)), (("a", "shared"), ("b", "shared")))
    dates = (((None,), (-1,)), ((-1,), (None,)), ((0,), (0,)), ((3, 1), (2,)))
    for left, right, preferred, grouping, times, retained in itertools.product(
        range(1, 4),
        range(1, 4),
        (False, True),
        groups,
        dates,
        (False, True),
    ):
        buckets = (key("history-0"), key("history-1"))
        inherited = {
            key(alias): frozenset(
                bucket for index, bucket in enumerate(buckets) if mask & (1 << index)
            )
            for alias, mask in (("a", left), ("b", right), ("shared", left | right))
        }
        bindings = {
            alias: sorted(values)[-1 if preferred else 0]
            for alias, values in inherited.items()
        }
        previous = peri_scribe.fire_updates.State(
            perimeters={
                bucket: frozenset({f"prior-{index}"})
                for index, bucket in enumerate(buckets)
            },
            aliases=bindings,
            lineage=inherited,
            owners={buckets[1]: buckets[0]} if retained else {},
        )
        fires = list(map(observation, grouping, times, strict=True))
        if retained:
            fires[0] = dataclasses.replace(
                fires[0],
                perimeters=(
                    *fires[0].perimeters,
                    dataclasses.replace(
                        fires[0].perimeters[0],
                        geometry=shapely.Polygon(),
                        observation_time=EPOCH,
                    ),
                ),
            )
        result.append(
            tests.formal.helpers.identity_lifecycle.publication_input(fires, previous),
        )
    return tuple(result)


def boundary_cases() -> tuple[Resolution, ...]:
    """Legacy direct buckets and provenance-only reservations also constrain allocation.

    Returns:
        Three cases whose histories are absent from ordinary alias/perimeter indexes.
    """
    fires = [observation(("a",), (1,))]
    return (
        tests.formal.helpers.identity_lifecycle.publication_input(
            fires,
            peri_scribe.fire_updates.State(owners={key("a"): key("orphan")}),
        ),
        tests.formal.helpers.identity_lifecycle.publication_input(
            fires,
            peri_scribe.fire_updates.State(
                lineage={key("absent"): frozenset({key("a")})},
            ),
        ),
        tests.formal.helpers.identity_lifecycle.publication_input(
            [*fires, observation(("b",), (2,))],
            peri_scribe.fire_updates.State(
                perimeters={key("a"): frozenset({"legacy"})},
                aliases={key("b"): key("a")},
            ),
        ),
    )


def check_batches() -> int:
    """Proved raw-claim and transfer operations drive every expected owner map.

    Returns:
        Number of complete unresolved batches compared with production.
    """
    references = tuple(
        Reference(case=case) for case in (*batch_cases(), *boundary_cases())
    )
    expected = claims(references)
    actual = tuple(
        map(ownership, references, expected, strict=True),
    )
    outcomes = tests.formal.helpers.oracle.evaluate(
        list(map(transfer_command, references, actual, strict=True)),
        executable="oracleIdentityTransfer",
    )
    for reference, selected, result in zip(references, actual, outcomes, strict=True):
        assert_owners(reference, selected, result)
    return len(references)


def record_text(
    reference: Reference,
    kind: str,
    records: typing.Mapping[str, typing.Iterable[str]],
) -> str:
    """Keep record provenance explicit while assigning opaque semantic evidence tokens.

    Args:
        reference: The shared exact-identity symbol table.
        kind: Perimeter, source, or name evidence namespace.
        records: Immutable buckets and their retained evidence.

    Returns:
        The executable oracle's history/evidence pairs.
    """
    return " ".join(
        f"{reference.token(history)},{reference.token(f'{kind}:{datum}')}"
        for history, data in sorted(records.items())
        for datum in sorted(data)
    )


def check_evidence(
    reference: Reference,
    actual: peri_scribe.fire_updates.Ownership,
    prepared: peri_scribe.fire_updates.PreparedUpdates,
) -> None:
    """Every checkpoint evidence field follows exact immutable-bucket acknowledgement.

    Args:
        reference: Raw previous checkpoint and current mapped/source observations.
        actual: Previously oracle-validated owner/writer assignments.
        prepared: Actual new records and checkpoint awaiting publication.
    """
    case = reference.case
    names = {
        identity: frozenset({peri_scribe.models.normalize_fire_name(fire.name)})
        for identity, fire in case.fires.items()
    }
    for kind, previous, current, observed in (
        (
            "perimeter",
            case.previous.perimeters,
            case.signatures,
            prepared.state.perimeters,
        ),
        ("source", case.previous.sources, case.sources, prepared.state.sources),
        (
            "name",
            tests.formal.helpers.identity_lifecycle.raw_history_names(case.previous),
            names,
            prepared.state.names,
        ),
    ):
        additions = {actual.keys[identity]: data for identity, data in current.items()}
        expected = tests.formal.helpers.oracle.evaluate(
            [
                "|".join((
                    "ack",
                    record_text(reference, kind, previous),
                    record_text(reference, kind, additions),
                )),
            ],
            executable="oracleIdentityTransfer",
        )[0]
        pairs = set(zip(expected[::2], expected[1::2], strict=True))
        assert set(observed) == set(previous) | set(additions)
        assert {
            (reference.token(history), reference.token(f"{kind}:{datum}"))
            for history, data in observed.items()
            for datum in data
        } == pairs
    novel = (
        tests.formal.helpers.oracle.evaluate(
            [
                "|".join((
                    "novel",
                    str(reference.token(actual.keys[identity])),
                    reference.owner_text(actual.owners),
                    record_text(reference, "perimeter", case.previous.perimeters),
                    " ".join(
                        str(reference.token(f"perimeter:{datum}"))
                        for datum in sorted(case.signatures[identity])
                    ),
                ))
                for identity in reference.identities
            ],
            executable="oracleIdentityTransfer",
        )
        if case.fires
        else []
    )
    expected_records = {
        actual.keys[identity]
        for identity, (changed,) in zip(reference.identities, novel, strict=True)
        if changed and not case.fires[identity].perimeters[-1].geometry.is_empty
    }
    assert {
        json.dumps(record["log_identity"]) for record in prepared.records
    } == expected_records


def encoded_lineage(
    reference: Reference,
    values: typing.Mapping[str, frozenset[str]],
) -> str:
    """Serialize already checked lineage without using any production resolver.

    Args:
        reference: The identity symbol table shared with the model.
        values: The previous result of monotone learning, initially raw saved lineage.

    Returns:
        The model's alias/history-list records.
    """
    return " ".join(
        f"{reference.token(alias)},"
        + (
            ":".join(str(reference.token(history)) for history in sorted(histories))
            or "n"
        )
        for alias, histories in sorted(values.items())
    )


def check_lineage(
    reference: Reference,
    actual: peri_scribe.fire_updates.Ownership,
    prepared: peri_scribe.fire_updates.PreparedUpdates,
) -> None:
    """Losing claims and inherited donor buckets remain learnable after correction.

    Args:
        reference: Complete unresolved publication inputs.
        actual: Oracle-validated current owner assignments and original claim sets.
        prepared: The production checkpoint proposed for acknowledgment.
    """
    expected = lineage(reference.case.previous)
    for identity in reference.identities:
        aliases = reference.aliases(identity)
        queries = sorted(set(expected) | set(aliases))
        result = iter(
            tests.formal.helpers.oracle.evaluate(
                [
                    "|".join((
                        "learn",
                        reference.sequence(queries),
                        reference.sequence(sorted(actual.owners)),
                        encoded_lineage(reference, expected),
                        reference.sequence(aliases),
                        reference.sequence(sorted(actual.claims[identity])),
                        reference.owner_text(actual.owners),
                        str(reference.token(actual.keys[identity])),
                    )),
                ],
                executable="oracleIdentityTransfer",
            )[0],
        )
        decoded = {token: key for key, token in reference.tokens.items()}
        expected = {
            alias: frozenset(decoded[next(result)] for _ in range(next(result)))
            for alias in queries
        }
        assert next(result, None) is None
    assert prepared.state.lineage == expected
    queries = sorted(
        set(reference.case.previous.aliases)
        | {
            alias
            for identity in reference.identities
            for alias in reference.aliases(identity)
        },
    )
    winners = tests.formal.helpers.oracle.evaluate(
        [
            "|".join((
                "claim",
                reference.sequence(queries),
                " ".join(
                    f"{reference.token(alias)},{reference.token(alias)}"
                    for alias in queries
                ),
                reference.fire_text(),
            )),
        ],
        executable="oracleIdentityTransfer",
    )[0]
    aliases = {
        alias: reference.case.previous.aliases[alias]
        if winner < 0
        else (actual.keys[reference.identities[winner - 1]])
        for alias, winner in zip(queries, winners, strict=True)
    }
    assert prepared.state.aliases == aliases
    assert prepared.state.owners == actual.owners


def publications() -> tuple[
    tuple[tuple[peri_scribe.presentation.fire_data.FireSummary, ...], ...],
    ...,
]:
    """Merge, split, absence, and reversals challenge evidence and visible grouping.

    Returns:
        Two complete publication sequences with distinct mapped observation identities.
    """
    first = observation(("a", "hidden"), (1,), name="Alpha")
    second = observation(("b",), (2,), name="Beta")
    merged = observation(("a", "b"), (3,), name="Merged")
    return (
        (
            (first, second),
            (merged,),
            (observation(("hidden",), (2,), name="Alpha"),),
            (
                observation(("a",), (4,), name="Alpha"),
                observation(("b",), (3,), name="Beta"),
            ),
            (
                observation(("a",), (4,), name="Alpha"),
                observation(("b",), (5,), name="Beta"),
            ),
            (
                observation(("a",), (6,), name="Alpha"),
                observation(("b",), (5,), name="Beta"),
            ),
            (),
            (observation(("a", "b", "hidden"), (1, 2, 3, 4, 5, 6), name="Rejoined"),),
        ),
        (
            (observation(("x", "y"), (1,), name="Old"),),
            (
                observation(("x",), (None,), name="Left"),
                observation(("y",), (0,), name="Right"),
            ),
            (
                observation(("x",), (2,), name="Left"),
                observation(("y",), (0,), name="Right"),
            ),
            (
                observation(("x", "xx-extra"), (3,), name="Left"),
                observation(("y", "yy-extra"), (3,), name="Right"),
            ),
            (
                observation(("x", "yy-extra"), (4,), name="Left"),
                observation(("y",), (3,), name="Right"),
            ),
        ),
    )


def check_snapshot(
    reference: Reference,
    directory: pathlib.Path,
    entries: tuple[peri_scribe.updates.LogEntry, ...],
    saved: peri_scribe.fire_updates.State,
) -> frozenset[tuple[str, str]]:
    """Actual viewer artifacts project immutable records through checked one-hop owners.

    Args:
        reference: Shared history tokens for this publication.
        directory: The isolated published year.
        entries: Complete retained real monthly JSONL records.
        saved: The reloaded acknowledged ownership checkpoint.

    Returns:
        Original bucket/current owner pairs actually present in the generated snapshot.
    """
    snapshot = peri_scribe.publication.read_state(
        directory / peri_scribe.paths.MAPS_DIRECTORY_NAME / "updates.json",
        peri_scribe.updates.Snapshot,
    )
    assert snapshot is not None
    projected = tests.formal.helpers.oracle.evaluate(
        [
            "|".join((
                "project",
                reference.owner_text(saved.owners),
                " ".join(
                    f"{reference.token(json.dumps(entry.identity()))},{index}"
                    for index, entry in enumerate(entries)
                ),
            )),
        ],
        executable="oracleIdentityTransfer",
    )[0]
    pairs = tuple(zip(projected[::2], projected[1::2], strict=True))
    assert tuple(index for _, index in pairs) == tuple(range(len(entries)))
    result = set()
    for update in snapshot.updates:
        original = peri_scribe.updates.LogEntry.model_validate(
            update.model_dump(exclude={"history_identity", "previous_mapped_area"}),
        )
        index = entries.index(original)
        assert update.history_identity is not None
        assert reference.token(json.dumps(update.history_identity)) == pairs[index][0]
        assert update.identity() == original.identity()
        result.add((
            json.dumps(original.identity()),
            json.dumps(update.history_identity),
        ))
    assert (directory / peri_scribe.paths.MAPS_DIRECTORY_NAME / "updates.html").exists()
    return frozenset(result)


def publish_round(
    directory: pathlib.Path,
    fires: list[peri_scribe.presentation.fire_data.FireSummary],
    previous: peri_scribe.fire_updates.State,
    round_index: int,
) -> tuple[peri_scribe.fire_updates.State, frozenset[tuple[str, str]]]:
    """Preparation, durable acknowledgment, and viewer publication share real inputs.

    Args:
        directory: The isolated year holding real checkpoint, journal, and viewer files.
        fires: Current observations in the chosen input order.
        previous: The previously reloaded acknowledged state.
        round_index: Publication-clock offset, independent of survey timestamps.

    Returns:
        The acknowledged checkpoint and visible original/current ownership pairs.
    """
    assert sum(len(fire.identifiers) for fire in fires) == len(
        set().union(*(fire.identifiers for fire in fires)),
    )
    case = tests.formal.helpers.identity_lifecycle.publication_input(fires, previous)
    reference = Reference(case=case)
    actual = ownership(reference, claims((reference,))[0])
    projected = tests.formal.helpers.oracle.evaluate(
        [
            transfer_command(reference, actual),
        ],
        executable="oracleIdentityTransfer",
    )[0]
    assert_owners(reference, actual, projected)
    scores = peri_scribe.models.FireScores(version="formal", fires=[])
    prepared = peri_scribe.fire_updates.prepare_updates(directory, fires, scores)
    repeated = peri_scribe.fire_updates.prepare_updates(
        directory,
        list(reversed(fires)),
        scores,
    )
    assert prepared.state == repeated.state
    assert tests.formal.helpers.identity_lifecycle.records_signature(
        prepared.records,
    ) == tests.formal.helpers.identity_lifecycle.records_signature(repeated.records)
    check_evidence(reference, actual, prepared)
    check_lineage(reference, actual, prepared)
    prior_entries = peri_scribe.updates.read_entries(directory)
    retained_bytes = {
        path: path.read_bytes() for path in (directory / "logs").glob("*.jsonl")
    }
    with time_machine.travel(EPOCH + datetime.timedelta(hours=round_index), tick=False):
        peri_scribe.fire_updates.write_updates(directory, prepared)
        entries = peri_scribe.updates.read_entries(directory)
        peri_scribe.fire_updates.write_updates(directory, prepared)
        assert peri_scribe.updates.read_entries(directory) == entries
        peri_scribe.updates.write_updates_page(directory)
    saved = peri_scribe.publication.read_state(
        peri_scribe.fire_updates.state_path(directory),
        peri_scribe.fire_updates.State,
    )
    assert saved == prepared.state
    assert saved is not None
    assert entries[: len(prior_entries)] == prior_entries
    assert len(entries) == len(prior_entries) + len(prepared.records)
    assert tests.formal.helpers.identity_lifecycle.records_signature(
        entry.model_dump(mode="json", exclude={"timestamp", "batch_id"})
        for entry in entries[len(prior_entries) :]
    ) == tests.formal.helpers.identity_lifecycle.records_signature(prepared.records)
    assert all(
        path.read_bytes().startswith(content)
        for path, content in retained_bytes.items()
    )
    retry = peri_scribe.fire_updates.prepare_updates(directory, fires, scores)
    assert retry.state == saved
    assert not retry.records
    return saved, check_snapshot(reference, directory, entries, saved)


def check_publications(directory: pathlib.Path) -> int:
    """Grouping can reverse while saved evidence and historical log bytes remain.

    Args:
        directory: Root for independent publication scenarios and input-order variants.

    Returns:
        Number of real publication rounds checked against the executable model.
    """
    count = 0
    for scenario, rounds in enumerate(publications()):
        for reverse in (False, True):
            previous = peri_scribe.fire_updates.State()
            projections = set()
            year = directory / f"case-{scenario}-{reverse}"
            for index, current in enumerate(rounds):
                fires = list(reversed(current)) if reverse else list(current)
                previous, visible = publish_round(year, fires, previous, index)
                projections.update(visible)
                count += 1
            assert any(original != owner for original, owner in projections)
    return count


def check_grouped_publication(directory: pathlib.Path) -> None:
    """Real source grouping supplies disjoint current aliases before publication retry.

    Args:
        directory: Isolated retained logs, checkpoints, and viewer outputs.
    """
    previous, _ = publish_round(
        directory,
        [
            observation(("x",), (1,), name="Alpha"),
            observation(("y",), (2,), name="Beta"),
        ],
        peri_scribe.fire_updates.State(),
        0,
    )
    source = [
        observation(("x", "zz-shared"), (3,), name="Alpha"),
        observation(("y", "zz-shared"), (3,), name="Beta"),
    ]
    grouped = tests.helpers.factories.peri_scribe.fire_updates_ownership.grouped_fires(
        source,
    )
    assert len(grouped) == 1
    assert grouped[0].identifiers == frozenset({"x", "y", "zz-shared"})
    saved, _ = publish_round(directory, grouped, previous, 1)
    assert set(previous.perimeters) <= set(saved.perimeters)
    assert len(set(saved.owners.values())) == 1
