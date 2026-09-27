"""Check the unbounded feedback executor against larger real checkpoint sequences."""

from __future__ import annotations

import dataclasses
import json
import pathlib
import typing

import peri_scribe.fire_updates
import peri_scribe.models
import peri_scribe.publication
import tests.formal.helpers.identity_lifecycle
import tests.formal.helpers.identity_transfer
import tests.formal.helpers.oracle


type AreaKey = tests.formal.helpers.identity_transfer.AreaKey
type Resolution = tests.formal.helpers.identity_lifecycle.Resolution
REPETITIONS = 3
COUNTS = (0, 1, 3, 5, 8, 16, 32, 64)
MODES = ("interleaved", "nested", "partitioned", "alternating", "adjacent", "fresh")


def cases(mode: str, seed: int) -> tuple[Resolution, ...]:
    """Combine competing routes with chains, cycles, dormant groups, and allocation.

    Args:
        mode: The raw relationship pattern for this independently checked batch.
        seed: Offset selecting its alias and ownership variations.

    Returns:
        Raw inputs independent of production resolution and acknowledgement helpers.
    """
    result = []
    for count in COUNTS:
        current = {
            ("id", f"fire-{fire:03}"): dataclasses.replace(
                tests.formal.helpers.identity_transfer.observation(
                    (f"fire-{fire:03}", f"fire-{fire:03}-other"),
                    (None,) if fire % 5 == 0 else (fire % 4 - 1, seed + fire % 7),
                    name=f"Current {fire}",
                ),
                component_id=f"component-{fire:03}",
                component_aliases=frozenset({f"component-{fire:03}-other"}),
            )
            for fire in range(count)
        }
        histories = [
            tests.formal.helpers.identity_transfer.key(f"history-{history:03}")
            for history in range(2 * count + 3)
        ]
        if mode == "fresh":
            histories.extend(json.dumps(identity) for identity in current)
        lineage = {}
        preferred = {}
        for fire, value in enumerate(current.values()):
            aliases = peri_scribe.fire_updates.identity_keys(value)
            for offset, alias in enumerate(aliases):
                lineage[alias] = frozenset(
                    history
                    for position, history in enumerate(histories[: 2 * count + 3])
                    if (
                        (
                            mode == "interleaved"
                            and (position + fire + offset + seed) % 3 == 0
                        )
                        or (mode == "nested" and position <= fire + offset)
                        or (mode == "partitioned" and position % (count + 1) == fire)
                        or (mode == "alternating" and position % 2 == offset % 2)
                        or (mode == "adjacent" and position in {fire, fire + 1})
                    )
                )
            if mode != "fresh" and fire % 2 == seed:
                preferred[aliases[0]] = histories[(fire + seed) % len(histories)]
        owners = {
            history: histories[
                (position + 1) % len(histories)
                if mode in {"interleaved", "partitioned", "adjacent"}
                else min(position + 1, len(histories) - 1)
            ]
            for position, history in enumerate(histories)
            if position % 4 != seed
        }
        result.append(
            tests.formal.helpers.identity_lifecycle.Resolution(
                fires=current,
                previous=peri_scribe.fire_updates.State(
                    perimeters={
                        history: frozenset({f"old-mapping-{position % 5}"})
                        for position, history in enumerate(histories)
                    },
                    sources={
                        history: frozenset({f"old-source-{position}"})
                        for position, history in enumerate(histories)
                        if position % 3 == 0
                    },
                    names={history: frozenset({"Archived"}) for history in histories},
                    aliases=preferred,
                    lineage=lineage,
                    owners=owners,
                ),
                signatures={
                    identity: frozenset(
                        peri_scribe.fire_updates.perimeter_signature(perimeter)
                        for perimeter in fire.perimeters
                    )
                    for identity, fire in current.items()
                },
                sources={
                    identity: frozenset(
                        reference
                        for perimeter in fire.perimeters
                        for reference in perimeter.source_references
                    )
                    for identity, fire in current.items()
                },
            ),
        )
    return tuple(result)


def number_text(values: typing.Iterable[int]) -> str:
    """Serialize tokens without interpreting ownership policy.

    Args:
        values: Naturals in protocol order.

    Returns:
        Space-delimited input for the compiled executor.
    """
    return " ".join(map(str, values))


@dataclasses.dataclass(kw_only=True)
class Execution:
    """A raw input and its actual outputs share one opaque-key symbol table."""

    reference: tests.formal.helpers.identity_transfer.Reference
    claims: dict[AreaKey, frozenset[str]]
    ownership: peri_scribe.fire_updates.Ownership
    fresh: dict[AreaKey, int] = dataclasses.field(default_factory=dict)

    def __post_init__(self) -> None:
        """Require unused distinct allocation tokens for the checked allocator."""
        known = tests.formal.helpers.identity_transfer.history_keys(
            self.reference.case.previous,
        )
        assert set(self.ownership.keys) == set(self.reference.case.fires)
        assert set(self.ownership.owners) == known | set(self.ownership.keys.values())
        assert len(set(self.ownership.keys.values())) == len(self.ownership.keys)
        for index, identity in enumerate(self.reference.identities):
            writer = self.ownership.keys[identity]
            if writer not in known:
                requested = json.dumps(identity)
                if requested not in known:
                    assert writer == requested
                else:
                    assert json.loads(writer)[0] == "local"
            self.fresh[identity] = self.reference.token(
                writer
                if writer not in known
                else json.dumps(("local", f"unused-{index}")),
            )
        assert len(set(self.fresh.values())) == len(self.fresh)
        assert not set(self.fresh.values()) & {
            self.reference.token(history) for history in known
        }

    @property
    def histories(self) -> tuple[str, ...]:
        """Query every retained bucket, including newly allocated writer buckets.

        Returns:
            Full actual output domain in deterministic order.
        """
        return tuple(sorted(self.ownership.owners))

    def command(self, count: int) -> str:
        """Run complete resolve, learn, acknowledge, and repeated resolution in Lean.

        Args:
            count: Number of already acknowledged feedback cycles.

        Returns:
            The raw input protocol; no production decision is used as a claim or owner.
        """
        reference = self.reference
        case = reference.case
        times = sorted({
            time
            for identity in reference.identities
            if (time := reference.mapped_time(identity)) is not None
        })
        return "|".join((
            str(count),
            reference.sequence(
                sorted(
                    tests.formal.helpers.identity_transfer.history_keys(case.previous),
                ),
            ),
            number_text(
                value
                for index, identity in enumerate(reference.identities)
                for time in [reference.mapped_time(identity)]
                for value in (
                    index,
                    int(time is not None),
                    times.index(time) if time is not None else 0,
                )
            ),
            number_text(
                value
                for index, identity in enumerate(reference.identities)
                for history in sorted(self.claims[identity])
                for value in (index, reference.token(history))
            ),
            number_text(
                value
                for index, identity in enumerate(reference.identities)
                if (preferred := reference.preferred(identity)) is not None
                for value in (index, reference.token(preferred))
            ),
            number_text(
                value
                for history, owner in sorted(case.previous.owners.items())
                for value in (reference.token(history), reference.token(owner))
            ),
            number_text(
                value
                for index, identity in enumerate(reference.identities)
                for value in (index, self.fresh[identity])
            ),
            number_text(
                value
                for history, evidence in sorted(case.previous.perimeters.items())
                for datum in sorted(evidence)
                for value in (
                    reference.token(history),
                    reference.token(f"mapping:{datum}"),
                )
            ),
            number_text(
                value
                for index, identity in enumerate(reference.identities)
                for datum in sorted(case.signatures[identity])
                for value in (index, reference.token(f"mapping:{datum}"))
            ),
            reference.sequence(self.histories),
        ))

    def observed(
        self,
        ownership: peri_scribe.fire_updates.Ownership,
        acknowledged: peri_scribe.fire_updates.State,
    ) -> tuple[int, ...]:
        """Read actual ownership, learned route sets, persisted evidence, and novelty.

        Args:
            ownership: Resolution from the checkpoint at this step.
            acknowledged: The actual state after acknowledging that resolution.

        Returns:
            The complete observed output in the executor's protocol order.
        """
        reference = self.reference
        values = [
            reference.token(ownership.keys[identity])
            for identity in reference.identities
        ]
        values.extend(
            reference.token(ownership.owners[history]) for history in self.histories
        )
        for identity in reference.identities:
            learned = set().union(
                *(acknowledged.lineage[alias] for alias in reference.aliases(identity)),
            )
            tokens = sorted(reference.token(history) for history in learned)
            values.extend((len(tokens), *tokens))
        for history in self.histories:
            tokens = sorted(
                reference.token(f"mapping:{datum}")
                for datum in acknowledged.perimeters.get(history, ())
            )
            values.extend((len(tokens), *tokens))
        for identity in reference.identities:
            inherited = frozenset(
                datum
                for history in ownership.histories[identity]
                for datum in acknowledged.perimeters.get(history, ())
            )
            values.append(int(bool(reference.case.signatures[identity] - inherited)))
        return tuple(values)


def check_sequences(directory: pathlib.Path, mode: str, seed: int) -> int:
    """Persist and recompute larger actual checkpoints against complete Lean executions.

    Args:
        directory: Isolated storage for checkpoints and prepared update states.
        mode: Relationship pattern covering every configured claimant count.
        seed: Alias and ownership offset for the selected pattern.

    Returns:
        The number of distinct raw checkpoints checked through all feedback cycles.
    """
    references = tuple(
        tests.formal.helpers.identity_transfer.Reference(case=case)
        for case in cases(mode, seed)
    )
    claims = tests.formal.helpers.identity_transfer.claims(references)
    commands = []
    outputs = []
    for index, (reference, expected) in enumerate(zip(references, claims, strict=True)):
        case = reference.case
        previous = case.previous
        ownership = peri_scribe.fire_updates.resolved_ownership(
            case.fires,
            previous,
            case.signatures,
            case.sources,
        )
        assert ownership.claims == expected[0]
        execution = Execution(
            reference=reference,
            claims=expected[0],
            ownership=ownership,
        )
        baseline = None
        case_directory = directory / str(index)
        for count in range(REPETITIONS + 1):
            if count:
                ownership = peri_scribe.fire_updates.resolved_ownership(
                    dict(reversed(tuple(case.fires.items()))),
                    previous,
                    case.signatures,
                    case.sources,
                )
            acknowledged = peri_scribe.fire_updates.acknowledged_state(
                case.fires,
                previous,
                ownership,
                case.signatures,
                case.sources,
            )
            commands.append(execution.command(count))
            outputs.append(execution.observed(ownership, acknowledged))
            if baseline is None:
                baseline = acknowledged
            else:
                assert acknowledged == baseline, (
                    index,
                    count,
                    "checkpoint fixed point",
                )
                assert ownership.keys == execution.ownership.keys
                assert ownership.owners == execution.ownership.owners
            path = peri_scribe.fire_updates.state_path(case_directory)
            peri_scribe.publication.write_state(path, acknowledged)
            previous = peri_scribe.publication.read_state(
                path,
                peri_scribe.fire_updates.State,
            )
            assert previous == acknowledged
        prepared = peri_scribe.fire_updates.prepare_updates(
            case_directory,
            list(case.fires.values()),
            peri_scribe.models.FireScores(version="test", fires=[]),
        )
        assert prepared.records == (), (index, "unchanged mapping reported again")
        assert prepared.state == baseline
    answers = tests.formal.helpers.oracle.evaluate(
        commands,
        executable="oracleIdentityRecomputation",
    )
    for index, (actual, expected) in enumerate(zip(outputs, answers, strict=True)):
        assert actual == expected, (
            index,
            "complete ownership feedback diverged",
            actual,
            expected,
        )
    return len(references)
