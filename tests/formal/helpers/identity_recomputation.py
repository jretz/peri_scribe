"""Replay the checked resolve, learn, acknowledge, and recompute state transitions."""

import dataclasses
import json
import pathlib
import re

import peri_scribe.fire_updates
import peri_scribe.presentation.fire_data
import peri_scribe.presentation.selection
import peri_scribe.publication
import tests.formal.helpers.identity_transfer
import tests.formal.helpers.tlc


type AreaKey = peri_scribe.presentation.selection.AreaKey
FIRE_COUNT = 2
HISTORY_COUNT = 2
MISSING = FIRE_COUNT + HISTORY_COUNT
KEYS = tuple(
    json.dumps(("id", value))
    for value in ("history-0", "history-1", "fire-0", "fire-1")
)


def mapping(value: str) -> dict[int, int]:
    """Decode exported scalar functions without repeating their selection policy.

    Args:
        value: A checked TLC finite function.

    Returns:
        Its numeric domain and range.
    """
    return {int(key): int(item) for key, item in re.findall(r"(\d+) :> (\d+)", value)}


def sets(value: str) -> dict[int, frozenset[int]]:
    """Preserve each checked set independently of dictionary ordering.

    Args:
        value: A TLC function with finite-set values.

    Returns:
        The checked membership sets.
    """
    return {
        int(key): frozenset(map(int, re.findall(r"\d+", members)))
        for key, members in re.findall(r"(\d+) :> \{([^}]*)\}", value)
    }


def successor(
    graph: tests.formal.helpers.tlc.Graph,
    node: int,
    action: str,
) -> int:
    """Require each concrete phase to follow the exported model edge.

    Args:
        graph: The complete checked transition graph.
        node: The state reached by the complete preceding execution.
        action: The concrete operation's abstract transition.

    Returns:
        Its unique checked successor.
    """
    edges = [edge for edge in graph.outgoing[node] if edge.action == action]
    assert len(edges) == 1, (node, action)
    return edges[0].target


@dataclasses.dataclass(frozen=True, kw_only=True)
class Case:
    """Disjoint current aliases retain all competing historical lineage routes."""

    fires: dict[AreaKey, peri_scribe.presentation.fire_data.FireSummary]
    signatures: dict[AreaKey, frozenset[str]]
    sources: dict[AreaKey, frozenset[str]]
    aliases: tuple[tuple[str, ...], ...]

    @property
    def identities(self) -> tuple[AreaKey, ...]:
        """Keep abstract priority consistent with mapped observation freshness.

        Returns:
            Current report identities from oldest to newest mapping.
        """
        return tuple(self.fires)

    def initial(self, state: dict[str, str]) -> peri_scribe.fire_updates.State:
        """Instantiate raw persisted associations independently of the resolver.

        Args:
            state: A checked initial model state.

        Returns:
            The equivalent valid production checkpoint.
        """
        routes = sets(state["lineage"])
        preferred = mapping(state["preferred"])
        owners = mapping(state["owners"])
        return peri_scribe.fire_updates.State(
            perimeters={
                KEYS[history]: self.signatures[self.identities[0]]
                for history in range(HISTORY_COUNT)
            },
            aliases={
                self.aliases[fire][0]: KEYS[history]
                for fire, history in preferred.items()
                if history != MISSING
            },
            lineage={
                alias: frozenset(KEYS[history] for history in routes[fire])
                for fire, aliases in enumerate(self.aliases)
                for alias in aliases
            },
            owners={
                KEYS[history]: KEYS[owner]
                for history, owner in owners.items()
                if history < HISTORY_COUNT
            },
        )

    def resolve(
        self,
        previous: peri_scribe.fire_updates.State,
    ) -> peri_scribe.fire_updates.Ownership:
        """Exercise the complete production allocator with current grouped inputs.

        Args:
            previous: The state before resolving the unchanged current fires.

        Returns:
            Production claims, writer allocation, and direct owners.
        """
        return peri_scribe.fire_updates.resolved_ownership(
            self.fires,
            previous,
            self.signatures,
            self.sources,
        )

    def acknowledge(
        self,
        previous: peri_scribe.fire_updates.State,
        ownership: peri_scribe.fire_updates.Ownership,
    ) -> peri_scribe.fire_updates.State:
        """Learn aliases and acknowledge evidence through the actual coordinator.

        Args:
            previous: The checkpoint supplying the existing evidence.
            ownership: The checked current ownership and writer allocation.

        Returns:
            The complete checkpoint ready for persistence.
        """
        return peri_scribe.fire_updates.acknowledged_state(
            self.fires,
            previous,
            ownership,
            self.signatures,
            self.sources,
        )

    def check_resolution(
        self,
        ownership: peri_scribe.fire_updates.Ownership,
        state: dict[str, str],
    ) -> None:
        """Compare allocated writers and all bucket owners with the TLC decision.

        Args:
            ownership: The actual resolved output.
            state: Its checked successor state.
        """
        assert ownership.keys == {
            self.identities[fire]: KEYS[writer]
            for fire, writer in mapping(state["writers"]).items()
        }
        assert {
            history: ownership.owners.get(KEYS[history], KEYS[history])
            for history in range(MISSING)
        } == {
            history: KEYS[owner] for history, owner in mapping(state["owners"]).items()
        }


def case() -> Case:
    """Include multiple aliases per fire without violating upstream grouping.

    Returns:
        Distinct current fires with increasing mapped observation dates.
    """
    fires = {
        ("id", f"fire-{fire}"): tests.formal.helpers.identity_transfer.observation(
            (f"fire-{fire}", f"fire-{fire}-alias"),
            (fire,),
        )
        for fire in range(FIRE_COUNT)
    }
    return Case(
        fires=fires,
        signatures={
            identity: frozenset(
                peri_scribe.fire_updates.perimeter_signature(perimeter)
                for perimeter in fire.perimeters
            )
            for identity, fire in fires.items()
        },
        sources={identity: frozenset() for identity in fires},
        aliases=tuple(
            tuple(
                json.dumps(("id", identifier))
                for identifier in sorted(fire.identifiers)
            )
            for fire in fires.values()
        ),
    )


def replay(
    graph: tests.formal.helpers.tlc.Graph,
    directory: pathlib.Path,
) -> int:
    """Connect complete checked paths to persistence and fresh recomputation.

    Args:
        graph: All checked routes, preferences, and owner arrangements.
        directory: Private storage for serialized checkpoint round trips.

    Returns:
        The number of realizable model initial states exercised.
    """
    inputs = case()
    count = 0
    for initial in graph.initial:
        state = graph.states[initial]
        routes = sets(state["lineage"])
        preferred = mapping(state["preferred"])
        # Persisted preferred aliases also contribute a route to their own bucket.
        if any(
            value != MISSING and value not in routes[fire]
            for fire, value in preferred.items()
        ):
            continue
        previous = inputs.initial(state)
        ownership = inputs.resolve(previous)
        node = successor(graph, initial, "Resolve")
        inputs.check_resolution(ownership, graph.states[node])
        acknowledged = inputs.acknowledge(previous, ownership)
        node = successor(graph, node, "Learn")
        learned = peri_scribe.fire_updates.history_lineage(acknowledged)
        assert {
            fire: frozenset(
                KEYS.index(history) for alias in aliases for history in learned[alias]
            )
            for fire, aliases in enumerate(inputs.aliases)
        } == sets(graph.states[node]["lineage"])
        assert {
            fire: KEYS.index(acknowledged.aliases[aliases[0]])
            for fire, aliases in enumerate(inputs.aliases)
        } == mapping(graph.states[node]["preferred"])
        node = successor(graph, node, "Acknowledge")
        evidence = sets(graph.states[node]["evidence"])
        assert {
            history: acknowledged.perimeters.get(KEYS[history], frozenset())
            for history in range(MISSING)
        } == {
            history: frozenset(
                signature
                for fire in members
                for signature in inputs.signatures[inputs.identities[fire]]
            )
            for history, members in evidence.items()
        }
        path = directory / f"{count}.json"
        peri_scribe.publication.write_state(path, acknowledged)
        restored = peri_scribe.publication.read_state(
            path,
            peri_scribe.fire_updates.State,
        )
        assert restored == acknowledged
        retried = inputs.resolve(restored)
        node = successor(graph, node, "Recompute")
        inputs.check_resolution(retried, graph.states[node])
        assert retried.keys == ownership.keys
        assert retried.owners == ownership.owners
        assert inputs.acknowledge(restored, retried) == restored
        for identity, signatures in inputs.signatures.items():
            inherited = frozenset(
                value
                for history in retried.histories[identity]
                for value in restored.perimeters.get(history, ())
            )
            assert signatures <= inherited
        count += 1
    return count
