"""Match observations to one TLC execution while retaining hidden-state choices.

Design notes:
[Verification evidence and execution](../../../docs/algorithms/verification-tooling.md).
"""

from __future__ import annotations

import collections.abc
import dataclasses
import typing


if typing.TYPE_CHECKING:
    import tests.formal.helpers.tlc


@dataclasses.dataclass(frozen=True, kw_only=True)
class Contract[Value: collections.abc.Hashable]:
    """Projection equality never creates an edge between unrelated abstract states."""

    graph: tests.formal.helpers.tlc.Graph
    values: dict[int, Value]
    actions: dict[tests.formal.helpers.tlc.Edge, str]
    internal: frozenset[str]

    def closure(self, candidates: frozenset[int], value: Value) -> frozenset[int]:
        """Allow explicitly internal actions only while observations stay unchanged.

        Args:
            candidates: Abstract states compatible with the entire preceding trace.
            value: The last observed concrete state.

        Returns:
            The compatible states after zero or more invisible internal actions.
        """
        reached = set(candidates)
        remaining = list(candidates)
        while remaining:
            source = remaining.pop()
            for edge in self.graph.outgoing.get(source, ()):
                if (
                    edge.target in self.values
                    and self.values[edge.target] == value
                    and self.actions[edge] in self.internal
                    and edge.target not in reached
                ):
                    reached.add(edge.target)
                    remaining.append(edge.target)
        return frozenset(reached)

    def start(self, value: Value) -> Path[Value]:
        """A concrete history must begin at a compatible model initial state.

        Args:
            value: Initial concrete durable contents.

        Returns:
            An initialized execution matcher.
        """
        candidates = frozenset(
            state
            for state in self.graph.initial
            if state in self.values and self.values[state] == value
        )
        assert candidates, ("no compatible TLC initial state", value)
        return Path(
            contract=self,
            candidates=self.closure(candidates, value),
            value=value,
        )


@dataclasses.dataclass(frozen=True, kw_only=True)
class Path[Value: collections.abc.Hashable]:
    """Keep every surviving full abstract state after the complete concrete prefix."""

    contract: Contract[Value]
    candidates: frozenset[int]
    value: Value
    observations: int = 1

    def observe(self, value: Value) -> Path[Value]:
        """Consume a visible mutation or a genuine unchanged concrete observation.

        Args:
            value: Contents observed after one separately durable operation.

        Returns:
            The remaining compatible execution prefixes.
        """
        if value == self.value:
            candidates = self.candidates
        else:
            candidates = frozenset(
                edge.target
                for source in self.candidates
                for edge in self.contract.graph.outgoing.get(source, ())
                if edge.target in self.contract.values
                and self.contract.values[edge.target] == value
                and self.contract.actions[edge] in self.contract.internal
            )
        assert candidates, (
            "no compatible TLC execution",
            self.observations,
            self.value,
            value,
        )
        return dataclasses.replace(
            self,
            candidates=self.contract.closure(candidates, value),
            value=value,
            observations=self.observations + 1,
        )

    def event(
        self,
        action: str,
        *,
        terminal_phases: frozenset[str] = frozenset(),
    ) -> Path[Value]:
        """Make crashes and environmental changes explicit even when bytes do not move.

        Args:
            action: The separately observed environment or lifecycle action.
            terminal_phases: Completed phases where process exit has no remaining work.

        Returns:
            Compatible successors, without spending an unobserved crash allowance.
        """
        return self.transition(action, self.value, terminal_phases=terminal_phases)

    def transition(
        self,
        action: str,
        value: Value,
        *,
        terminal_phases: frozenset[str] = frozenset(),
    ) -> Path[Value]:
        """Bind an explicit control event to its actual observed persistent effect.

        Args:
            action: The separately observed action, including its selected parameters.
            value: Concrete state after the event's independently durable effect.
            terminal_phases: Completed phases permitting an unchanged process exit.

        Returns:
            Compatible successors from the same complete preceding execution.
        """
        candidates = {
            edge.target
            for source in self.candidates
            for edge in self.contract.graph.outgoing.get(source, ())
            if edge.target in self.contract.values
            and self.contract.values[edge.target] == value
            and self.contract.actions[edge] == action
        }
        candidates.update(
            source
            for source in self.candidates
            if value == self.value
            and self.contract.graph.states[source].get("phase") in terminal_phases
        )
        assert candidates, ("no compatible TLC event", action, self.value, value)
        return dataclasses.replace(
            self,
            candidates=self.contract.closure(frozenset(candidates), value),
            value=value,
            observations=self.observations + 1,
        )
