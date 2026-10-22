"""Match real supervision and stage acknowledgments to complete checked TLC paths."""

from __future__ import annotations

import dataclasses
import os
import pathlib
import re
import typing
import unittest.mock

import peri_scribe.cli_options
import peri_scribe.pipeline
import peri_scribe.pipeline_stages
import peri_scribe.pipeline_state
import peri_scribe.supervision
import tests.formal.helpers.paths
import tests.formal.helpers.tlc
import tests.helpers.factories.peri_scribe.supervision


type Value = tuple[
    str,
    str,
    bool,
    bool,
    int,
    int,
    tuple[int, ...],
    tuple[int, ...],
    bool,
    str,
    str,
    bool,
]
STAGES = tuple(
    peri_scribe.pipeline_stages.Stage(name) for name in ("geography", "score", "kmz")
)


class Scenario(typing.TypedDict, total=False):
    """Select external effects without replacing supervisor or stage decisions."""

    skip: bool
    failure: int
    cancellation: int
    launch_failure: int
    bad_response: int


def sequence(value: str) -> tuple[int, ...]:
    """Decode the finite stage sequence exported by TLC.

    Args:
        value: TLC's exact sequence rendering.

    Returns:
        Its stage positions in order.
    """
    return tuple(map(int, re.findall(r"\d+", value)))


def contract(
    graph: tests.formal.helpers.tlc.Graph,
) -> tests.formal.helpers.paths.Contract[Value]:
    """Bind every model variable and retain the complete checked transition graph.

    Args:
        graph: The successful StageProcesses graph for the current proof session.

    Returns:
        Exact projections without hidden lifecycle transitions.
    """
    return tests.formal.helpers.paths.Contract(
        graph=graph,
        values={
            identifier: (
                state["parent"].strip('"'),
                state["child"].strip('"'),
                state["parentLease"] == "TRUE",
                state["childLease"] == "TRUE",
                int(state["segment"]),
                int(state["nextStage"]),
                sequence(state["completed"]),
                sequence(state["pending"]),
                state["required"] == "TRUE",
                state["response"].strip('"'),
                state["outcome"].strip('"'),
                state["competitor"] == "TRUE",
            )
            for identifier, state in graph.states.items()
        },
        actions={
            edge: edge.action for edges in graph.outgoing.values() for edge in edges
        },
        internal=frozenset(),
    )


def live(descriptor: int | None) -> bool:
    """Observe a still-open lease reference rather than inferring it from intent.

    Args:
        descriptor: An owned descriptor, or None outside its scope.

    Returns:
        Whether the descriptor still denotes its actual file.
    """
    if descriptor is None:
        return False
    try:
        os.fstat(descriptor)
    except OSError:
        return False
    return True


@dataclasses.dataclass(kw_only=True)
class Replay:
    """Control process transport while the actual coordinator chooses both segments."""

    year: pathlib.Path
    checked: tests.formal.helpers.paths.Contract[Value]
    skip: bool = False
    failure: int | None = None
    cancellation: int | None = None
    launch_failure: int | None = None
    bad_response: int | None = None
    parent: str = "new"
    child: str = "none"
    descriptor: int | None = None
    inherited: int | None = None
    segment: int = 1
    completed: list[int] = dataclasses.field(default_factory=list)
    response: str = "none"
    outcome: str = "pending"
    competitor: bool = False
    execution: tests.formal.helpers.paths.Path[Value] = dataclasses.field(init=False)

    def value(self) -> Value:
        """Read actual descriptor liveness and pending files alongside observed calls.

        Returns:
            All abstract variables bound to this concrete execution.
        """
        state = peri_scribe.pipeline_state.read_state(self.year)
        pending = tuple(STAGES.index(stage) + 1 for stage in state.remaining)
        return (
            self.parent,
            self.child,
            live(self.descriptor),
            live(self.inherited),
            self.segment,
            len(self.completed) + 1,
            tuple(self.completed),
            pending,
            not self.skip,
            self.response,
            self.outcome,
            self.competitor,
        )

    def observe(self, action: str) -> None:
        """Require the whole prior concrete history to admit this actual transition.

        Args:
            action: The separately observed model lifecycle or durable-file action.
        """
        self.execution = self.execution.transition(action, self.value())

    def stage(
        self,
        stage: peri_scribe.pipeline.PipelineStage,
        year: pathlib.Path,
        **_options: object,
    ) -> bool:
        """Replace domain work with a durable local receipt or a controlled failure.

        Args:
            stage: The production loop's selected phase.
            year: Its actual isolated output directory.
            _options: Real flags and publication inputs forwarded by that loop.

        Returns:
            The controlled fetch continuation decision.

        Raises:
            KeyboardInterrupt: At the selected cancellation boundary.
            RuntimeError: At the selected failed domain stage.
        """
        if stage.name is peri_scribe.pipeline_stages.Stage.FETCH:
            return not self.skip
        index = STAGES.index(stage.name) + 1
        with peri_scribe.pipeline_state.read_lock(year) as acquired:
            assert acquired
        if self.cancellation == index:
            raise KeyboardInterrupt
        if self.failure == index:
            message = "Controlled stage failure"
            raise RuntimeError(message)
        (year / f"stage-{index}").write_text(str(index))
        return True

    def child_transport(
        self,
        request: peri_scribe.supervision.Request,
        descriptor: int,
        _directory: pathlib.Path,
    ) -> peri_scribe.supervision.SegmentResult:
        """Run actual selected-stage policy under a real duplicated inherited lease.

        Args:
            request: The actual supervisor's chosen range and initialization flag.
            descriptor: Its continuously held parent lease.
            _directory: Private transport storage owned by the actual supervisor.

        Returns:
            The real stage loop's continuation response.

        Raises:
            OSError: When the controlled process launch fails.
        """
        if not request.initialize:
            assert (
                request.start
                == peri_scribe.cli_options.STAGE_INDEX[
                    peri_scribe.pipeline_stages.Stage.SCORE
                ]
            )
            self.segment = 2
            self.child = "none"
            self.response = "none"
            self.observe("Continue")
        if self.launch_failure == self.segment:
            self.parent = "joining"
            self.outcome = "error"
            self.observe("LaunchFailure")
            message = "Controlled launch failure"
            raise OSError(message)
        self.inherited = os.dup(descriptor)
        try:
            result = self.execute_child(request)
        except BaseException:
            self.inherited = None
            self.child = "stopped"
            self.response = "invalid"
            self.observe("Settle" if self.parent == "joining" else "ChildFailure")
            raise
        self.inherited = None
        self.child = "stopped"
        self.response = (
            "continue"
            if result.next_stage is not None
            else ("complete" if self.completed else "skip")
        )
        self.observe("Skip" if self.response == "skip" else "ChildSuccess")
        return result

    def execute_child(
        self,
        request: peri_scribe.supervision.Request,
    ) -> peri_scribe.supervision.SegmentResult:
        """Keep the duplicated lease live across actual stage policy and interruption.

        Args:
            request: The coordinator's actual selected segment.

        Returns:
            The completed real segment response.
        """
        assert self.inherited is not None
        with peri_scribe.pipeline_state.inherited_lease(self.year, self.inherited):
            self.child = "running"
            self.observe("Launch")
            result = self.execute_segment(request)
            self.validate_response()
            return result

    def execute_segment(
        self,
        request: peri_scribe.supervision.Request,
    ) -> peri_scribe.supervision.SegmentResult:
        """Observe cancellation before its child's lease is closed by unwinding.

        Args:
            request: The actual selected stage segment.

        Returns:
            The real stage loop result.

        Raises:
            KeyboardInterrupt: After recording the independently injected cancellation.
        """
        try:
            return peri_scribe.supervision.execute_request(request)
        except KeyboardInterrupt:
            self.parent = "joining"
            self.outcome = "cancelled"
            self.observe("Cancel")
            raise

    def validate_response(self) -> None:
        """Reject a selected malformed handoff after domain work has completed.

        Raises:
            ValueError: When this child was configured to return invalid transport data.
        """
        if self.bad_response == self.segment:
            message = "Controlled malformed response"
            raise ValueError(message)

    def run(self) -> None:
        """Exercise success and failure through the real coordinator."""
        self.year.mkdir()
        if not self.skip:
            peri_scribe.pipeline_state.require_stages(
                self.year,
                STAGES,
                unconditional=True,
            )
        self.execution = self.checked.start(self.value())
        complete = peri_scribe.pipeline_state.complete_stage

        def acknowledge(
            year: pathlib.Path,
            stage: peri_scribe.pipeline_stages.Stage,
        ) -> None:
            """Observe each actual durable stage acknowledgment separately.

            Args:
                year: The isolated year whose recovery marker was updated.
                stage: The stage the real loop just completed successfully.
            """
            complete(year, stage)
            if stage in STAGES:
                self.completed.append(STAGES.index(stage) + 1)
                self.observe("CompleteStage")

        request = tests.helpers.factories.peri_scribe.supervision.request(
            self.year,
        ).model_copy(
            update={
                "start": 0 if self.skip else 1,
                "end": 3,
                "unconditional": not self.skip,
            },
        )
        with (
            unittest.mock.patch.object(
                peri_scribe.supervision,
                "run_child",
                self.child_transport,
            ),
            unittest.mock.patch.object(
                peri_scribe.pipeline,
                "run_pipeline_stage",
                self.stage,
            ),
            unittest.mock.patch.object(
                peri_scribe.pipeline_state,
                "complete_stage",
                acknowledge,
            ),
        ):
            with peri_scribe.pipeline_state.run_lease(self.year) as descriptor:
                assert descriptor is not None
                self.descriptor = descriptor
                self.parent = "active"
                self.observe("Acquire")
                try:
                    peri_scribe.supervision.supervise(request, descriptor)
                except KeyboardInterrupt, OSError, RuntimeError, ValueError:
                    if self.parent == "active":
                        self.parent = "joining"
                        self.outcome = "error"
                        self.observe("Finish")
                else:
                    self.parent = "joining"
                    self.outcome = "success"
                    self.observe("Finish")
            self.descriptor = None
            self.parent = "released"
            self.observe("Release")
        with peri_scribe.pipeline_state.run_lock(self.year) as acquired:
            assert acquired
            self.competitor = True
            self.observe("Compete")
        self.competitor = False
        self.observe("CompetitorExit")
