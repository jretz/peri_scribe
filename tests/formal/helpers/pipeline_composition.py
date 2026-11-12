"""Connect composed TLC invocations to real coordinator and durable file effects.

Design notes:
[Verification evidence and execution](../../../docs/algorithms/verification-tooling.md).
"""

import collections
import collections.abc
import contextlib
import dataclasses
import datetime
import functools
import json
import pathlib
import re

import pytest
import structlog
import time_machine

import peri_scribe.durable_file
import peri_scribe.fires.differential
import peri_scribe.fires.index
import peri_scribe.fires.scores
import peri_scribe.kml.builder
import peri_scribe.logging
import peri_scribe.paths
import peri_scribe.pipeline
import peri_scribe.pipeline_stages
import peri_scribe.pipeline_state
import peri_scribe.preparation
import peri_scribe.publication
import peri_scribe.sources.fetching
import tests.formal.helpers.paths
import tests.formal.helpers.pipeline_replay_files
import tests.formal.helpers.pipeline_state
import tests.formal.helpers.tlc
import tests.helpers.doubles.peri_scribe.pipeline_fetch_recovery
import tests.helpers.factories.peri_scribe.publication


KMZ = peri_scribe.pipeline.STAGE_INDEX[peri_scribe.pipeline_stages.Stage.KMZ]
BATCH_COUNT = 48
REPLAY_INVOCATION_COUNT = 38143
BASELINE_MAPPING = tests.helpers.factories.peri_scribe.publication.mapping(100)
SMALL_CHANGE_MAPPING = tests.helpers.factories.peri_scribe.publication.mapping(
    110,
    serial=2,
)
THRESHOLD_CHANGE_MAPPING = tests.helpers.factories.peri_scribe.publication.mapping(
    125,
    serial=2,
)


@dataclasses.dataclass(frozen=True, kw_only=True)
class Durable:
    """Source and output generations retain independently persisted obligations."""

    source: int
    outputs: tuple[int, ...]
    pending: peri_scribe.pipeline_state.PendingRun
    deferred: bool
    kmz_version: int
    publication_version: int
    publication: int


@dataclasses.dataclass(frozen=True, kw_only=True)
class Invocation:
    """A checked invocation includes its selected policy and process-loss boundary."""

    before: Durable
    after: Durable
    first: int
    last: int
    gated: bool
    forced: bool
    changed: bool
    threshold: bool
    current: int
    failed_at: str
    executed: tuple[int, ...]
    forces: tuple[bool, ...]


def sequence(value: str) -> tuple[str, ...]:
    """Preserve the order of stages and their effective forcing decisions.

    Args:
        value: A TLC sequence containing scalar values.

    Returns:
        The individual values without TLC delimiters.
    """
    assert value.startswith("<<"), value
    assert value.endswith(">>"), value
    return tuple(item.strip() for item in value[2:-2].split(",") if item.strip())


def durable(value: str) -> Durable:
    """Require every durable field to be present in TLC's exported record.

    Args:
        value: A durable state record emitted by TLC.

    Returns:
        The exact source, derivation, marker, and checkpoint state.
    """
    pending = re.search(r"pending \|-> (\[[^\]]+\])", value)
    outputs = re.search(r"outputs \|-> (<<[^>]+>>)", value)
    assert pending is not None, value
    assert outputs is not None, value
    scalars = dict(re.findall(r"(\w+) \|-> (TRUE|FALSE|-?\d+)", value))
    return Durable(
        source=int(scalars["source"]),
        outputs=tuple(int(item) for item in sequence(outputs[1])),
        pending=tests.formal.helpers.pipeline_state.state(pending[1]),
        deferred=scalars["deferred"] == "TRUE",
        kmz_version=int(scalars["kmzVersion"]),
        publication_version=int(scalars["publicationVersion"]),
        publication=int(scalars["publication"]),
    )


@dataclasses.dataclass(frozen=True, kw_only=True)
class Executions:
    """Every retained outcome includes its real path from the unique initial state."""

    checked: tests.formal.helpers.paths.Contract[Durable]
    histories: dict[Invocation, tuple[Invocation, ...]]


def begin_action(
    first: int,
    last: int,
    *,
    gated: bool,
    forced: bool,
    changed: bool,
    threshold: bool,
) -> str:
    """Invocation choices are observed control events, never hidden closure steps.

    Args:
        first: First selected stage.
        last: Last selected stage.
        gated: Whether publication gating applies.
        forced: Whether this invocation forces its stages.
        changed: Whether collection changes the source inventory.
        threshold: Whether the modeled change reaches the publication threshold.

    Returns:
        An exact action identity carrying every selected model input.
    """
    return f"begin:{first}:{last}:{gated}:{forced}:{changed}:{threshold}"


def invocation(
    fields: dict[str, str],
    parse_durable: collections.abc.Callable[[str], Durable],
) -> Invocation:
    """Retain the existing complete invocation contract from a checked terminal node.

    Args:
        fields: One actual TLC terminal state.
        parse_durable: The current graph's parser for immutable durable records.

    Returns:
        Its original controls, stage calls, crash boundary, and final durable state.
    """
    return Invocation(
        before=parse_durable(fields["before"]),
        after=parse_durable(fields["durable"]),
        first=int(fields["first"]),
        last=int(fields["last"]),
        gated=fields["gated"] == "TRUE",
        forced=fields["forced"] == "TRUE",
        changed=fields["changed"] == "TRUE",
        threshold=fields["threshold"] == "TRUE",
        current=int(fields["current"]),
        failed_at=json.loads(fields["failedAt"]),
        executed=tuple(int(item) for item in sequence(fields["executed"])),
        forces=tuple(item == "TRUE" for item in sequence(fields["stageForces"])),
    )


def executions(graph: tests.formal.helpers.tlc.Graph) -> Executions:
    """Recover complete predecessor executions for every checked invocation outcome.

    Args:
        graph: Complete checked graph shared by every batch in this run.

    Returns:
        The directed contract and one history from an initial state to each distinct
        invocation outcome.
    """
    parse_durable = functools.cache(durable)
    previous: dict[int, int | None] = dict.fromkeys(graph.initial)
    queue = collections.deque(graph.initial)
    while queue:
        node = queue.popleft()
        for edge in graph.outgoing.get(node, ()):
            if edge.target not in previous:
                previous[edge.target] = node
                queue.append(edge.target)
    actions = {}
    for edges in graph.outgoing.values():
        for edge in edges:
            fields = graph.states[edge.target]
            action = json.loads(fields["action"])
            actions[edge] = (
                begin_action(
                    int(fields["first"]),
                    int(fields["last"]),
                    gated=fields["gated"] == "TRUE",
                    forced=fields["forced"] == "TRUE",
                    changed=fields["changed"] == "TRUE",
                    threshold=fields["threshold"] == "TRUE",
                )
                if action == "begin"
                else action
            )
    checked = tests.formal.helpers.paths.Contract(
        graph=dataclasses.replace(
            graph,
            states={
                node: {"phase": fields["phase"]}
                for node, fields in graph.states.items()
            },
        ),
        values={
            node: parse_durable(fields["durable"])
            for node, fields in graph.states.items()
        },
        actions=actions,
        internal=frozenset({
            "start fetch",
            "consume deferred",
            "fetch",
            "finish fetch",
            "execute",
            "commit",
            "invalidate",
            "acknowledge",
        }),
    )
    terminals = {
        node: invocation(fields, parse_durable)
        for node, fields in graph.states.items()
        if fields["phase"] == '"done"'
    }
    records = {}
    for node, record in terminals.items():
        if record in records:
            continue
        history = []
        current: int | None = node
        while current is not None:
            if current in terminals:
                history.append(terminals[current])
            current = previous[current]
        records[record] = tuple(reversed(history))
    assert collections.Counter(record.failed_at for record in records) == {
        "": 7328,
        "stage": 3970,
        "acknowledge": 3895,
        "fetch write": 840,
        "fetch decide": 840,
        "fetch consume": 795,
        "commit publication": 786,
        "invalidate publication": 786,
    }
    assert {(record.first, record.last) for record in records} == {
        (first, last) for first in range(5) for last in range(first, 5)
    }
    assert {record.gated for record in records} == {False, True}
    assert {record.forced for record in records} == {False, True}
    assert any(
        record.before.deferred and record.before.source != record.before.outputs[0]
        for record in records
    )
    assert any(
        record.before.pending.unconditional and record.before.pending.remaining
        for record in records
    )
    assert sum(map(len, records.values())) == REPLAY_INVOCATION_COUNT
    return Executions(checked=checked, histories=records)


@dataclasses.dataclass(kw_only=True)
class Replay:
    """Keep actual byte observations connected to one compatible execution."""

    invocation: Invocation
    directory: pathlib.Path
    memory: tests.formal.helpers.pipeline_replay_files.Memory | None = None
    trace: list[tests.formal.helpers.pipeline_replay_files.Event] | None = None
    calls: list[int] = dataclasses.field(default_factory=list)
    forces: list[bool] = dataclasses.field(default_factory=list)
    execution: tests.formal.helpers.paths.Path[Durable] | None = None
    begun: bool = False
    files: tests.formal.helpers.pipeline_replay_files.Artifacts = dataclasses.field(
        init=False,
    )
    source_file: pathlib.Path = dataclasses.field(init=False)
    output_files: tuple[pathlib.Path, ...] = dataclasses.field(init=False)
    deferred_file: pathlib.Path = dataclasses.field(init=False)
    checkpoint_file: pathlib.Path = dataclasses.field(init=False)

    def __post_init__(self) -> None:
        """Build fixture paths once so each observation can read them directly."""
        self.files = tests.formal.helpers.pipeline_replay_files.Artifacts(
            directory=self.directory,
            memory=self.memory,
            trace=self.trace,
        )
        self.source_file = self.directory / "source-generation"
        self.output_files = tuple(
            peri_scribe.paths.kmz_path(self.directory)
            if stage == KMZ
            else self.directory / f"output-{stage}"
            for stage in range(1, 5)
        )
        self.deferred_file = peri_scribe.pipeline_state.deferred_inputs_path(
            self.directory,
        )
        self.checkpoint_file = peri_scribe.publication.publication_path(self.directory)

    def snapshot(self) -> Durable:
        """Read each independently retained file without consulting the expected result.

        Returns:
            Actual source/output generations, recovery markers, and checkpoint identity.
        """
        try:
            checkpoint_bytes = self.files.read_bytes(self.checkpoint_file)
        except FileNotFoundError:
            checkpoint = None
        else:
            checkpoint = peri_scribe.publication.Publication.model_validate_json(
                checkpoint_bytes,
            )
        return Durable(
            source=int(self.files.read_bytes(self.source_file)),
            outputs=tuple(
                int(self.files.read_bytes(path)) for path in self.output_files
            ),
            pending=peri_scribe.pipeline_state.read_state(self.directory),
            deferred=self.files.exists(self.deferred_file),
            kmz_version=self.files.modified_nanoseconds(self.output_path(KMZ))
            // 1_000_000_000
            - 1,
            publication_version=-1
            if checkpoint is None
            else (checkpoint.output.modified_nanoseconds // 1_000_000_000 - 1),
            publication=-1 if checkpoint is None else len(checkpoint.files) - 1,
        )

    def begin(
        self,
        checked: tests.formal.helpers.paths.Contract[Durable],
        execution: tests.formal.helpers.paths.Path[Durable] | None,
    ) -> None:
        """Start at Init or continue the preceding completed concrete invocation.

        Args:
            checked: The complete model contract.
            execution: The preceding actual invocation, when present.
        """
        if execution is None:
            self.initialize()
            value = self.snapshot()
            self.execution = checked.start(value)
        else:
            self.execution = execution.event("next")
            value = self.snapshot()
            assert value == self.invocation.before
        if not (
            self.invocation.last > 0
            and (self.invocation.forced or self.invocation.first > 0)
        ):
            self.observe(value)

    def inspect(self) -> None:
        """Public persistence boundaries continue the same set of abstract paths."""
        if self.execution is None:
            return
        self.observe(self.snapshot())

    def observe(self, value: Durable) -> None:
        """A control-only transition can reuse the immediately preceding observation.

        Args:
            value: Actual file contents read without any intervening persistence.
        """
        assert self.execution is not None
        if self.trace is not None:
            self.trace.append(
                tests.formal.helpers.pipeline_replay_files.Observation(
                    image=self.files.image(),
                ),
            )
        if self.begun:
            self.execution = self.execution.observe(value)
        else:
            selected = self.invocation
            self.execution = self.execution.transition(
                begin_action(
                    selected.first,
                    selected.last,
                    gated=selected.gated,
                    forced=selected.forced,
                    changed=selected.changed,
                    threshold=selected.threshold,
                ),
                value,
            )
            self.begun = True

    def install_observer(self, patch: pytest.MonkeyPatch) -> None:
        """Observe independently durable marker and checkpoint replacements/removals.

        Args:
            patch: Isolated observers that preserve actual filesystem behavior.
        """
        watched = {
            peri_scribe.pipeline_state.state_path(self.directory),
            self.deferred_file,
            self.checkpoint_file,
        }
        original_replace, original_unlink, original_touch = (
            pathlib.Path.replace,
            pathlib.Path.unlink,
            pathlib.Path.touch,
        )

        def replace(path: pathlib.Path, target: pathlib.Path) -> pathlib.Path:
            """Retain atomic publication before observing its new durable value.

            Args:
                path: The staged file.
                target: The actual publication destination.

            Returns:
                The unchanged filesystem replacement result.
            """
            before = self.files.effect_input() if target in watched else None
            argument = path.read_bytes() if before is not None else b""
            result = original_replace(path, target)
            if target in watched:
                self.files.record_effect(
                    tests.formal.helpers.pipeline_replay_files.Operation.REPLACE,
                    target,
                    argument=argument,
                    before=before,
                )
                self.inspect()
            return result

        def unlink(path: pathlib.Path, *, missing_ok: bool = False) -> None:
            """Acknowledgments and checkpoint invalidation remain separate effects.

            Args:
                path: The independently retired marker.
                missing_ok: The unchanged production absence policy.
            """
            before = self.files.effect_input() if path in watched else None
            original_unlink(path, missing_ok=missing_ok)
            if path in watched:
                self.files.record_effect(
                    tests.formal.helpers.pipeline_replay_files.Operation.REMOVE,
                    path,
                    argument=missing_ok,
                    before=before,
                )
                self.inspect()

        def touch(
            path: pathlib.Path,
            mode: int = 0o666,
            *,
            exist_ok: bool = True,
        ) -> None:
            """Collection intent is observed before source mutation can begin.

            Args:
                path: The deferred-input marker.
                mode: The requested creation mode.
                exist_ok: The requested existing-file policy.
            """
            before = self.files.effect_input() if path in watched else None
            original_touch(path, mode=mode, exist_ok=exist_ok)
            if path in watched:
                self.files.record_effect(
                    tests.formal.helpers.pipeline_replay_files.Operation.TOUCH,
                    path,
                    argument=exist_ok,
                    before=before,
                )
                self.inspect()

        patch.setattr(pathlib.Path, "replace", replace)
        patch.setattr(pathlib.Path, "unlink", unlink)
        patch.setattr(pathlib.Path, "touch", touch)

    def source_path(self) -> pathlib.Path:
        """Keep collected generations separate from every derived output.

        Returns:
            The isolated source generation file.
        """
        return self.source_file

    def output_path(self, stage: int) -> pathlib.Path:
        """Use the real KMZ location so checkpoint identity validation remains active.

        Args:
            stage: The model's derived-stage number.

        Returns:
            The corresponding independently written artifact.
        """
        return self.output_files[stage - 1]

    def inputs(self, generation: int) -> peri_scribe.publication.Collection:
        """Give the actual gate either below-threshold or threshold-reaching changes.

        Args:
            generation: The source revision to represent in the inventory.

        Returns:
            Source observations with stable baseline identity and distinct new files.
        """
        candidate = (
            THRESHOLD_CHANGE_MAPPING
            if self.invocation.threshold
            else SMALL_CHANGE_MAPPING
        )
        return tests.helpers.factories.peri_scribe.publication.collection(
            BASELINE_MAPPING,
            *((candidate,) if generation else ()),
        )

    def collect(self, directory: pathlib.Path) -> peri_scribe.publication.Collection:
        """Read the persisted source generation so the gate observes stored inputs.

        Args:
            directory: The year supplied by the production coordinator.

        Returns:
            The saved source inventory for that year.
        """
        assert directory == self.directory
        return self.inputs(int(self.files.read_bytes(self.source_path())))

    def fires(
        self,
        generation: int,
    ) -> dict[str, peri_scribe.publication.PublishedFire]:
        """Retain actual mapped-area comparisons against the last published revision.

        Args:
            generation: The input revision used for the completed map.

        Returns:
            The included fire baseline matching that revision.
        """
        collection = self.inputs(generation)
        latest = collection.mappings[f"snapshot-{generation + 1}"][0]
        return tests.helpers.factories.peri_scribe.publication.publication(latest).fires

    def write_kmz(self, generation: int, version: int) -> None:
        """Observe the completed KMZ before changing its publication checkpoint.

        Args:
            generation: The geography revision encoded by this artifact.
            version: The model version for the completed KMZ identity.
        """
        self.files.write_generation(
            self.output_path(KMZ),
            str(generation).encode(),
            (version + 1) * 1_000_000_000,
        )
        self.inspect()

    def initialize(self) -> None:
        """Recreate exactly the durable state reached by prior modeled invocations."""
        before = self.invocation.before
        if self.memory is None:
            self.directory.mkdir(parents=True)
        self.files.write_generation(self.source_path(), str(before.source).encode())
        for stage, generation in enumerate(before.outputs, start=1):
            if stage == KMZ:
                self.write_kmz(generation, before.kmz_version)
            else:
                self.files.write_generation(
                    self.output_path(stage),
                    str(generation).encode(),
                )
        peri_scribe.pipeline_state.write_state(self.directory, before.pending)
        if before.deferred:
            peri_scribe.pipeline_state.defer_inputs(self.directory)
        if before.publication >= 0:
            checkpoint = peri_scribe.publication.Publication(
                created_at=tests.helpers.factories.peri_scribe.publication.NOW,
                output=peri_scribe.publication.FileStamp(
                    size=1,
                    modified_nanoseconds=(before.publication_version + 1)
                    * 1_000_000_000,
                ),
                files=self.inputs(before.publication).files,
                fires=self.fires(before.publication),
            )
            peri_scribe.publication.write_state(
                self.checkpoint_file,
                checkpoint,
            )

    def fetch(
        self,
        _base: pathlib.Path,
        *,
        year: int,
        full: bool,
        build_index: bool = True,
    ) -> peri_scribe.sources.fetching.FetchResult:
        """Keep interruption points on both sides of persistent source mutation.

        Args:
            _base: Root accepted by the production fetcher.
            year: Requested calendar year.
            full: Whether a scheduled full fetch was requested.
            build_index: Whether collection may immediately build the index.

        Returns:
            The actual fetch result type with the chosen durable change indication.
        """
        assert year == int(self.directory.name)
        assert not full
        assert build_index != self.invocation.gated
        self.interrupt("fetch write")
        if self.invocation.changed:
            self.files.write_generation(self.source_path(), b"1")
        self.inspect()
        self.interrupt("fetch decide")
        return peri_scribe.sources.fetching.FetchResult(
            snapshot_paths=(),
            changed=self.invocation.changed,
        )

    def interrupt(self, boundary: str) -> None:
        """A simulated interruption bypasses ordinary exception handlers.

        Args:
            boundary: The persistent transition about to execute.

        Raises:
            ProcessLoss: When this case selects the given failure boundary.
        """
        if self.invocation.failed_at == boundary:
            if self.trace is not None:
                self.trace.append(
                    tests.formal.helpers.pipeline_replay_files.Failure(
                        boundary=boundary,
                        image=self.files.image(),
                    ),
                )
            raise tests.helpers.doubles.peri_scribe.pipeline_fetch_recovery.ProcessLoss

    def geography(self, directory: pathlib.Path, *, unconditional: bool) -> None:
        """Represent completed geography independently of collection and KMZ writes.

        Args:
            directory: The selected year.
            unconditional: The effective requirement sent through the real stage.
        """
        assert directory == self.directory
        assert unconditional == self.forces[-1]
        self.files.write_generation(
            self.output_path(1),
            self.files.read_bytes(self.source_path()),
        )
        self.inspect()

    def score(self, directory: pathlib.Path) -> None:
        """Scoring consumes prepared geography rather than the current source inventory.

        Args:
            directory: The selected year.
        """
        assert directory == self.directory
        self.files.write_generation(
            self.output_path(2),
            self.files.read_bytes(self.output_path(1)),
        )
        self.inspect()

    def reports(self, directory: pathlib.Path) -> pathlib.Path:
        """Reports consume prepared geography rather than bypassing prerequisite work.

        Args:
            directory: The selected year.

        Returns:
            The independently persisted report.
        """
        assert directory == self.directory
        self.files.write_generation(
            self.output_path(4),
            self.files.read_bytes(self.output_path(1)),
        )
        self.inspect()
        return self.output_path(4)

    def create_kmz(
        self,
        directory: pathlib.Path,
        *,
        publication_inputs: peri_scribe.publication.Collection | None = None,
    ) -> pathlib.Path:
        """Keep KMZ replacement separate from committing its frozen publication inputs.

        Args:
            directory: The selected year.
            publication_inputs: The source inventory frozen after real stage dispatch.

        Returns:
            The completed KMZ path.
        """
        assert directory == self.directory
        self.write_kmz(
            int(self.files.read_bytes(self.output_path(1))),
            self.invocation.before.kmz_version + 1,
        )
        self.interrupt("commit publication")
        if publication_inputs is not None:
            generation = len(publication_inputs.files) - 1
            peri_scribe.publication.commit(
                directory,
                self.output_path(3),
                publication_inputs,
                self.fires(generation),
            )
        self.interrupt("invalidate publication")
        return self.output_path(3)

    def check(self) -> None:
        """Compare every observable durable component with TLC's terminal state."""
        expected = self.invocation.after
        assert tuple(self.calls) == self.invocation.executed, self.invocation
        assert tuple(self.forces) == self.invocation.forces, self.invocation
        if self.trace is not None:
            self.trace.append(
                tests.formal.helpers.pipeline_replay_files.Calls(
                    stages=tuple(self.calls),
                    forces=tuple(self.forces),
                ),
            )
        assert self.execution is not None
        assert self.execution.value == expected, self.invocation
        output = self.output_path(3)
        assert (
            self.files.modified_nanoseconds(output)
            == (expected.kmz_version + 1) * 1_000_000_000
        )
        path = self.checkpoint_file
        if expected.publication < 0:
            assert not self.files.exists(path), self.invocation
        else:
            checkpoint = peri_scribe.publication.Publication.model_validate_json(
                self.files.read_bytes(path),
            )
            assert checkpoint.files == self.inputs(expected.publication).files
            assert (
                checkpoint.output.modified_nanoseconds
                == (expected.publication_version + 1) * 1_000_000_000
            )
        valid = peri_scribe.publication.read_publication(self.directory, output)
        assert (valid is not None) == (
            expected.publication >= 0
            and expected.publication_version == expected.kmz_version
        ), self.invocation


def install_dependencies(scenario: Replay, monkeypatch: pytest.MonkeyPatch) -> None:
    """Substitute data-producing stages while preserving actual coordinator decisions.

    Args:
        scenario: Fixture producers bound to this invocation's durable files.
        monkeypatch: Overrides scoped to the invocation.
    """
    monkeypatch.setattr(
        peri_scribe.sources.fetching,
        "fetch_all_feeds",
        scenario.fetch,
    )
    monkeypatch.setattr(peri_scribe.publication, "collect", scenario.collect)
    monkeypatch.setattr(
        peri_scribe.fires.differential,
        "write_history_of_differential_geography",
        scenario.geography,
    )
    monkeypatch.setattr(peri_scribe.fires.scores, "score_fires", scenario.score)
    monkeypatch.setattr(peri_scribe.kml.builder, "create_kmz", scenario.create_kmz)
    monkeypatch.setattr(peri_scribe.pipeline, "write_reports", scenario.reports)
    monkeypatch.setattr(
        peri_scribe.pipeline,
        "prepare_administrative_boundaries",
        lambda _year: None,
    )
    monkeypatch.setattr(
        peri_scribe.fires.index,
        "index_fire_sources",
        lambda _year: None,
    )
    monkeypatch.setattr(
        peri_scribe.pipeline,
        "fetch_external_source",
        lambda _source, _year: None,
    )
    monkeypatch.setattr(
        peri_scribe.pipeline,
        "refresh_external_sources",
        lambda _year, **_kwargs: False,
    )
    monkeypatch.setattr(
        peri_scribe.preparation,
        "scope",
        lambda *_args, **_kwargs: contextlib.nullcontext(),
    )
    monkeypatch.setattr(
        peri_scribe.logging,
        "log_phase",
        lambda *_args, **_kwargs: contextlib.nullcontext(),
    )
    monkeypatch.setattr(peri_scribe.logging, "skip_phases", lambda *_args: None)
    logger = structlog.ReturnLogger()
    monkeypatch.setattr(peri_scribe.pipeline, "logger", logger)
    monkeypatch.setattr(peri_scribe.pipeline_state, "state_logger", lambda: logger)


def replay(
    invocation: Invocation,
    directory: pathlib.Path,
    checked: tests.formal.helpers.paths.Contract[Durable],
    execution: tests.formal.helpers.paths.Path[Durable] | None = None,
    *,
    memory: tests.formal.helpers.pipeline_replay_files.Memory | None = None,
    trace: list[tests.formal.helpers.pipeline_replay_files.Event] | None = None,
) -> tests.formal.helpers.paths.Path[Durable]:
    """Execute real selected stages, pending markers, and checkpoint decisions.

    Args:
        invocation: TLC's exact input and terminal output for one composed invocation.
        directory: Isolated year directory containing this case's persistent files.
        checked: The full checked transition graph and durable projection.
        execution: The preceding real invocation, or None for the model initialization.
        memory: Private in-memory raw files when replaying the complete cross-product.
        trace: Optional ordered record for direct comparison with physical execution.

    Returns:
        The continuing execution matcher after this real invocation.
    """
    scenario = Replay(
        invocation=invocation,
        directory=directory,
        memory=memory,
        trace=trace,
    )
    run_stage = peri_scribe.pipeline.run_pipeline_stage
    complete_stage = peri_scribe.pipeline_state.complete_stage
    clear_deferred = peri_scribe.pipeline_state.clear_deferred_inputs

    def run(
        stage: peri_scribe.pipeline.PipelineStage,
        year: pathlib.Path,
        *,
        full_fetch_interval: datetime.timedelta | None,
        unconditional: bool,
        publish_threshold: peri_scribe.publication.Threshold | None = None,
        publication_inputs: peri_scribe.publication.Collection | None = None,
    ) -> bool:
        """Record actual dispatch and preserve the production stage implementation.

        Args:
            stage: Selected stage and its phase description.
            year: Selected year directory.
            full_fetch_interval: The unchanged scheduling policy.
            unconditional: The actual effective force flag supplied by the coordinator.
            publish_threshold: The invocation's publication policy.
            publication_inputs: Inputs frozen by the coordinator after geography.

        Returns:
            The real stage's decision to continue.
        """
        index = peri_scribe.pipeline.STAGE_INDEX[stage.name]
        if index == invocation.current:
            scenario.interrupt("stage")
        scenario.calls.append(index)
        scenario.forces.append(unconditional)
        return run_stage(
            stage,
            year,
            full_fetch_interval=full_fetch_interval,
            unconditional=unconditional,
            publish_threshold=publish_threshold,
            publication_inputs=publication_inputs,
        )

    def complete(year: pathlib.Path, stage: peri_scribe.pipeline_stages.Stage) -> None:
        """Keep completed artifacts separate from their pending-work acknowledgment.

        Args:
            year: The year whose recovery marker is being updated.
            stage: The completed stage.
        """
        if peri_scribe.pipeline.STAGE_INDEX[stage] == invocation.current:
            scenario.interrupt("acknowledge")
        complete_stage(year, stage)

    def clear(year: pathlib.Path) -> None:
        """Simulate an interruption after all pending stages protect deferred inputs.

        Args:
            year: The year whose durable intent is being consumed.
        """
        scenario.interrupt("fetch consume")
        clear_deferred(year)

    with (
        pytest.MonkeyPatch.context() as monkeypatch,
        # The coordinator reads UTC explicitly. Freezing the instant keeps the local
        # timezone and its process-wide settings out of the replay.
        time_machine.travel(
            tests.helpers.factories.peri_scribe.publication.NOW.timestamp(),
            tick=False,
        ),
    ):
        if memory is not None:
            memory.trace = trace
            memory.observe = scenario.inspect
            monkeypatch.setattr(peri_scribe.durable_file, "at", memory.at)
        elif trace is not None:
            scenario.install_observer(monkeypatch)
        scenario.begin(checked, execution)
        if memory is None and trace is None:
            scenario.install_observer(monkeypatch)
        monkeypatch.setattr(peri_scribe.pipeline, "run_pipeline_stage", run)
        monkeypatch.setattr(peri_scribe.pipeline_state, "complete_stage", complete)
        monkeypatch.setattr(peri_scribe.pipeline_state, "clear_deferred_inputs", clear)
        install_dependencies(scenario, monkeypatch)
        with (
            pytest.raises(
                tests.helpers.doubles.peri_scribe.pipeline_fetch_recovery.ProcessLoss,
            )
            if invocation.failed_at
            else contextlib.nullcontext()
        ):
            peri_scribe.pipeline.run_selected_stages(
                directory,
                invocation.first,
                invocation.last,
                full_fetch_interval=None,
                unconditional=invocation.forced,
                publish_threshold=(
                    tests.helpers.factories.peri_scribe.publication.THRESHOLD
                    if invocation.gated
                    else None
                ),
            )
        scenario.inspect()
        assert scenario.execution is not None
        if invocation.failed_at:
            scenario.execution = scenario.execution.event("crash")
        scenario.check()
    return scenario.execution
