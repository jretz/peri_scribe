"""Match observable session versions and subscriptions to checked TLC executions."""

import dataclasses
import pathlib
import re
import typing

import tests.formal.helpers.corpus
import tests.formal.helpers.paths


if typing.TYPE_CHECKING:
    import peri_scribe.monitor.session


type Observation = tuple[bool, bool, int, tuple[int, ...], tuple[int, ...]]


def contract(
    directory: pathlib.Path,
) -> tests.formal.helpers.paths.Contract[Observation]:
    """Retain compatible complete states across subscription and publication changes.

    Args:
        directory: This formal invocation's isolated evidence directory.

    Returns:
        The checked directed graph projected onto public session observations.
    """
    graph = tests.formal.helpers.corpus.graph(
        "MonitorSession",
        "MonitorSession",
        directory,
    )
    actions = {edge: edge.action for edges in graph.outgoing.values() for edge in edges}
    return tests.formal.helpers.paths.Contract(
        graph=graph,
        values={
            identifier: (
                state["stopped"] == "TRUE",
                state["closed"] == "TRUE",
                int(state["version"]),
                tuple(sorted(map(int, re.findall(r"\d+", state["connected"])))),
                tuple(map(int, re.findall(r"-?\d+", state["received"]))),
            )
            for identifier, state in graph.states.items()
        },
        actions=actions,
        internal=frozenset(actions.values()),
    )


@dataclasses.dataclass(frozen=True, kw_only=True)
class Observer:
    """Remember actual returned versions independently of the subscription mailbox."""

    session: peri_scribe.monitor.session.MonitorSession
    subscriptions: dict[int, peri_scribe.monitor.session.Subscription] = (
        dataclasses.field(default_factory=dict)
    )
    received: dict[int, int] = dataclasses.field(default_factory=lambda: {1: -1, 2: -1})

    def observation(self) -> Observation:
        """Read domain ownership and delivered results without inventing model actions.

        Returns:
            The concrete projection compared with the actual checked graph.
        """
        return (
            self.session.owner.stopped.is_set(),
            self.session.owner.closed.is_set(),
            self.session.snapshot.version,
            tuple(
                identifier
                for identifier, subscription in sorted(self.subscriptions.items())
                if subscription in self.session.subscriptions
            ),
            tuple(self.received[identifier] for identifier in sorted(self.received)),
        )

    async def receive(self, identifier: int) -> None:
        """Observe a real subscriber's next complete version.

        Args:
            identifier: The independently scheduled subscriber.
        """
        snapshot = await self.subscriptions[identifier].receive()
        assert snapshot is self.session.snapshot
        self.received[identifier] = snapshot.version
