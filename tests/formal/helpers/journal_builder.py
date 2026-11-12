"""Exercise builder crash boundaries while retaining the real persistence stack.

Design notes:
[Verification evidence and execution](../../../docs/algorithms/verification-tooling.md).
"""

import base64
import collections
import dataclasses
import datetime
import functools
import importlib
import json
import pathlib
import re
import shutil
import tempfile
import zipfile

import geopandas
import pydantic
import structlog.testing
import time_machine

import peri_scribe.fire_updates
import peri_scribe.fires.derived_layers
import peri_scribe.fires.index
import peri_scribe.fires.score_files
import peri_scribe.kml.builder
import peri_scribe.kml.fire_data
import peri_scribe.kml.icons
import peri_scribe.models
import peri_scribe.paths
import peri_scribe.pipeline_state
import peri_scribe.preparation
import peri_scribe.previews
import peri_scribe.publication
import peri_scribe.report.gathering
import peri_scribe.updates
import tests.formal.helpers.corpus
import tests.formal.helpers.journal
import tests.formal.helpers.journal_builder_inputs
import tests.formal.helpers.journal_wire_observer
import tests.formal.helpers.paths
import tests.formal.helpers.session
import tests.formal.helpers.tlc
import tests.helpers.doubles.attribute_overrides
import tests.helpers.factories.peri_scribe.fire_updates
from measurement_units import units


type Projection = tests.formal.helpers.journal_wire_observer.Projection
GENERATION_COUNT = tests.formal.helpers.journal_wire_observer.GENERATION_COUNT
RECORDS_PER_GENERATION = (
    tests.formal.helpers.journal_wire_observer.RECORDS_PER_GENERATION
)
MINIMUM_OBSERVATIONS = 20
ROTATION_DESTINATIONS = frozenset({"archive", "unlink plain"})
ICON_CONTENT = base64.b64decode(
    "iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAYAAAAfFcSJAAAADUlEQVR4nGNgYGBgAAAABQAB"
    "pfZFQAAAAABJRU5ErkJggg==",
)


@dataclasses.dataclass(frozen=True, kw_only=True)
class ModeEvidence:
    """Keep the initial states, observations, and ordered edges for one mode."""

    mode: tuple[bool, ...]
    observations: tuple[tuple[int, Projection, str], ...]
    initial: frozenset[int]
    outgoing: tuple[tuple[int, tuple[tuple[int, str], ...]], ...]


MODE_EVIDENCE = pydantic.TypeAdapter(tuple[ModeEvidence, ...])


def projections(
    directory: pathlib.Path,
) -> dict[tuple[bool, ...], tests.formal.helpers.paths.Contract[Projection]]:
    """Project every checked nonempty-batch state to observable file generations.

    Args:
        directory: An isolated TLC export directory.

    Returns:
        Directed execution contracts, separated by exact publication modes.
    """
    if (session := tests.formal.helpers.session.directory()) is None:
        return full_projections(directory)
    evidence = tests.formal.helpers.corpus.load(
        session,
        "journal-publication-modes",
        MODE_EVIDENCE,
        build_modes,
    )
    return {mode.mode: restore_mode(mode) for mode in evidence}


def full_projections(
    directory: pathlib.Path,
) -> dict[tuple[bool, ...], tests.formal.helpers.paths.Contract[Projection]]:
    """Validate the complete publication graph before selecting its builder modes.

    Args:
        directory: An isolated TLC export directory.

    Returns:
        Every builder mode with its original checked publication graph.
    """
    replay = tests.formal.helpers.corpus.graph(
        "JournalReplay",
        "JournalReplay",
        directory,
    )
    return contracts(publication_graph(replay))


def build_modes(directory: pathlib.Path) -> tuple[ModeEvidence, ...]:
    """Retain each builder's possible states and edges after full graph validation.

    Args:
        directory: Private staging storage for this evidence producer.

    Returns:
        Immutable match inputs for every checked builder mode.
    """
    modes = []
    for mode, contract in full_projections(directory).items():
        outgoing = []
        for source in contract.values:
            targets = tuple(
                (edge.target, contract.actions[edge])
                for edge in contract.graph.outgoing.get(source, ())
                if edge.target in contract.values
            )
            if targets:
                outgoing.append((source, targets))
        modes.append(
            ModeEvidence(
                mode=mode,
                observations=tuple(
                    (node, value, contract.graph.states[node]["phase"])
                    for node, value in contract.values.items()
                ),
                initial=contract.graph.initial.intersection(contract.values),
                outgoing=tuple(outgoing),
            ),
        )
    return tuple(modes)


def restore_mode(
    evidence: ModeEvidence,
) -> tests.formal.helpers.paths.Contract[Projection]:
    """Restore the matcher inputs that can occur after this mode's initial states.

    Args:
        evidence: Complete ordered observations and successors for the mode.

    Returns:
        A contract with its own maps and the original observable actions.
    """
    outgoing = {}
    actions = {}
    for source, targets in evidence.outgoing:
        edges = []
        for target, action_name in targets:
            edge = tests.formal.helpers.tlc.Edge(
                source=source,
                target=target,
                action="Next",
            )
            actions[edge] = action_name
            edges.append(edge)
        outgoing[source] = tuple(edges)
    return tests.formal.helpers.paths.Contract(
        graph=tests.formal.helpers.tlc.Graph(
            states={node: {"phase": phase} for node, _, phase in evidence.observations},
            initial=evidence.initial,
            outgoing=outgoing,
        ),
        values={node: value for node, value, _ in evidence.observations},
        actions=actions,
        internal=frozenset({"step"}),
    )


def publication_graph(
    replay: tests.formal.helpers.tlc.Graph,
) -> tests.formal.helpers.tlc.Graph:
    """Retain the complete publication graph before any recovery observation begins.

    Args:
        replay: The complete checked graph, including uninterrupted recovery branches.

    Returns:
        The states and transitions of the original publication specification.
    """
    observers = ("recoveryInput", "recoveryAge", "replaying", "recovered")
    base = {
        identifier: fields
        for identifier, fields in replay.states.items()
        if fields["replaying"] == "FALSE"
    }
    assert replay.initial <= base.keys(), "publication must own every initial state"
    observer_values = {
        tuple(fields[name] for name in observers) for fields in base.values()
    }
    assert len(observer_values) == 1, "publication states must share fixed observers"
    states = {
        identifier: {
            name: value for name, value in fields.items() if name not in observers
        }
        for identifier, fields in base.items()
    }
    outgoing = {}
    for identifier, edges in replay.outgoing.items():
        if identifier not in states:
            assert all(edge.target not in states for edge in edges)
            continue
        retained = []
        for edge in edges:
            if edge.target in states:
                assert edge.action == "Explore"
                retained.append(dataclasses.replace(edge, action="Next"))
            else:
                assert edge.action == "BeginRecovery"
        if retained:
            outgoing[identifier] = tuple(retained)
    return tests.formal.helpers.tlc.Graph(
        states=states,
        initial=replay.initial,
        outgoing=outgoing,
    )


def contracts(
    graph: tests.formal.helpers.tlc.Graph,
) -> dict[tuple[bool, ...], tests.formal.helpers.paths.Contract[Projection]]:
    """Retain exact publication modes while reusing one complete checked graph.

    Args:
        graph: The complete UpdateJournal graph exported by a successful TLC run.

    Returns:
        Directed execution contracts separated by exact publication modes.
    """
    parse_modes = functools.cache(publication_modes)
    parse_durable = functools.cache(publication_projection)
    allowed: dict[tuple[bool, ...], dict[int, Projection]] = collections.defaultdict(
        dict,
    )
    for identifier, fields in graph.states.items():
        if fields["hasRecords"] != "<<TRUE, TRUE>>":
            continue
        fresh_inputs = parse_modes(fields["publicationModes"])
        if fresh_inputs is not None:
            allowed[fresh_inputs][identifier] = parse_durable(fields["durable"])
    assert set(allowed) == {
        (False, False),
        (False, True),
        (True, False),
        (True, True),
    }
    premature = (1, 0, 1, 0, 0, (0, 0), (0, 0), False)
    assert premature in allowed[False, False].values()
    assert premature not in allowed[True, True].values()
    actions = {
        edge: action(graph.states[edge.source], graph.states[edge.target])
        for edges in graph.outgoing.values()
        for edge in edges
    }
    return {
        mode: tests.formal.helpers.paths.Contract(
            graph=graph,
            values=states,
            actions=actions,
            internal=frozenset({"step"}),
        )
        for mode, states in allowed.items()
    }


def publication_modes(text: str) -> tuple[bool, ...] | None:
    """Extract the complete input mode from one immutable TLC field.

    Returns:
        The ordered fresh-input flags, or None for a gated mode.
    """
    if "gated |-> TRUE" in text:
        return None
    return tuple(
        value == "TRUE" for value in re.findall(r"freshInputs \|-> (TRUE|FALSE)", text)
    )


def publication_projection(text: str) -> Projection:
    """Extract every observed durable publication field from one TLC record.

    Returns:
        The exact ordered publication projection used by the matcher.
    """
    scalars = dict(re.findall(r"(\w+) \|-> (\d+)", text))
    state = tests.formal.helpers.journal.durable(text)
    return (
        int(scalars["kmz"]),
        int(scalars["publication"]),
        state.journal,
        state.checkpoint,
        int(scalars["viewer"]),
        state.plain,
        state.archive,
        "rotationReceipt |-> TRUE" in text,
    )


def action(before: dict[str, str], after: dict[str, str]) -> str:
    """Classify environment edges without inventing successors absent from TLC.

    Args:
        before: The actual exported source node.
        after: The actual exported successor node.

    Returns:
        A separate observable control event or an ordinary implementation step.
    """
    for field, event in (
        ("failures", "crash"),
        ("oldMonth", "age"),
        ("target", "batch"),
    ):
        if before[field] != after[field]:
            return event
    return "step"


@dataclasses.dataclass(kw_only=True)
class Scenario(tests.formal.helpers.journal_wire_observer.Scenario):
    """Retain real states and timestamps while abstracting expensive input rendering."""

    allowed: tests.formal.helpers.paths.Contract[Projection] | None = dataclasses.field(
        repr=False,
    )
    execution: tests.formal.helpers.paths.Path[Projection] | None = None
    aged: bool = False
    checks: int = 0

    def branch(self, directory: pathlib.Path) -> Scenario:
        """Continue one exact checked prefix in an independent year tree.

        Args:
            directory: The new year directory for a single continuation.

        Returns:
            The copied concrete state and full surviving model path.
        """
        assert self.execution is not None
        shutil.copytree(self.directory, directory)
        copied = dataclasses.replace(
            self,
            directory=directory,
            states={
                number: state.model_copy(deep=True)
                for number, state in self.states.items()
            },
            timestamps=self.timestamps.copy(),
            batch_ids=self.batch_ids.copy(),
            viewer_times=self.viewer_times.copy(),
        )
        assert copied.snapshot() == self.execution.value
        assert peri_scribe.publication.file_stamp(
            peri_scribe.paths.kmz_path(copied.directory),
        ) == peri_scribe.publication.file_stamp(
            peri_scribe.paths.kmz_path(self.directory),
        )
        return copied

    def inspect(self) -> None:
        """Require the entire concrete prefix to follow one checked abstract path."""
        actual = self.snapshot()
        assert self.allowed is not None
        assert actual in self.allowed.values.values(), actual
        self.execution = (
            self.allowed.start(actual)
            if self.execution is None
            else self.execution.observe(actual)
        )
        self.checks += 1

    def event(self, name: str) -> None:
        """Keep explicit crashes, collection generations, and clock changes in the path.

        Args:
            name: The concrete environment event between filesystem observations.
        """
        assert self.execution is not None
        self.execution = self.execution.event(
            name,
            terminal_phases=frozenset({'"done"'}) if name == "crash" else frozenset(),
        )


def geometries(generation: int) -> list[peri_scribe.kml.fire_data.FireGeometry]:
    """Provide two independently logged fires for the current generation.

    Args:
        generation: The generation providing new mapped evidence.

    Returns:
        Fixed valid polygons with new survey evidence and distinguishable areas.
    """
    base = tests.helpers.factories.peri_scribe.fire_updates.mapped_fire()
    return [
        peri_scribe.kml.fire_data.FireGeometry(
            name=f"Fire {number}",
            identifiers=frozenset({f"fire-{number}"}),
            status=base.status,
            point=None,
            type_one=True,
            perimeters=(
                dataclasses.replace(
                    base.perimeters[0],
                    observation_time=tests.formal.helpers.journal.EPOCH
                    + datetime.timedelta(seconds=generation),
                    area=(100 * generation + number) * units.acres,
                ),
            ),
        )
        for number in range(2)
    ]


def report(
    fires: list[peri_scribe.kml.fire_data.FireGeometry],
    _scores: peri_scribe.models.FireScores,
    _directory: pathlib.Path,
) -> peri_scribe.report.gathering.FireReport:
    """Supply report selection without geocoding or presentation dependencies.

    Args:
        fires: Current prepared geometry summaries.
        _scores: Irrelevant scoring input for these Type 1 fixtures.
        _directory: The unused geocoding data location.

    Returns:
        Both fires selected for the real update preparation and identity code.
    """
    details = tuple(
        peri_scribe.report.gathering.FireReportEntry(
            name=fire.name,
            identifier=next(iter(fire.identifiers)),
            status=fire.status,
        )
        for fire in fires
    )
    return peri_scribe.report.gathering.FireReport(
        new_notable_fires=(),
        type_one_fires=details,
        fastest_growing_by_acres=(),
        fastest_growing_by_percent=(),
        top_fires=(),
        fire_details=details,
    )


def install(
    monkeypatch: tests.helpers.doubles.attribute_overrides.AttributePatch,
    scenario: tests.formal.helpers.journal_wire_observer.Scenario,
) -> None:
    """Stub only input preparation and rendering, retaining builder ordering and I/O.

    Args:
        monkeypatch: Scoped overrides for this scenario.
        scenario: The generation and independently checked allowed states.
    """
    empty = geopandas.GeoDataFrame(geometry=[], crs="EPSG:4326")
    monkeypatch.setattr(
        peri_scribe.fires.index,
        "load_fire_index",
        lambda _year: peri_scribe.models.FireIndex(version="formal", fires=[]),
    )
    monkeypatch.setattr(
        peri_scribe.fires.score_files,
        "load_fire_scores",
        lambda _year: None,
    )
    monkeypatch.setattr(
        peri_scribe.fires.derived_layers,
        "read_derived_layers",
        lambda *_args, **_kwargs: peri_scribe.fires.derived_layers.DerivedLayers(
            perimeters=empty,
            points=empty,
            differential_perimeters=empty,
        ),
    )
    monkeypatch.setattr(
        peri_scribe.kml.fire_data,
        "fire_geometries",
        lambda *_args, **_kwargs: geometries(scenario.generation),
    )
    monkeypatch.setattr(
        peri_scribe.publication,
        "published_fires",
        lambda *_args, **_kwargs: {},
    )
    monkeypatch.setattr(peri_scribe.report.gathering, "report_from_fires", report)
    monkeypatch.setattr(
        peri_scribe.previews,
        "fire_preview",
        lambda _fire: tests.formal.helpers.journal.PREVIEWS[scenario.generation - 1],
    )
    monkeypatch.setattr(
        peri_scribe.kml.icons,
        "interior_progression_icon",
        lambda: ICON_CONTENT,
    )
    monkeypatch.setattr(
        peri_scribe.kml.icons,
        "perimeters_icon",
        lambda: ICON_CONTENT,
    )
    monkeypatch.setattr(
        peri_scribe.kml.icons,
        "outlined_perimeter_icon",
        lambda _color: ICON_CONTENT,
    )
    # Each scenario owns isolated products in an immutable runtime. Source/runtime
    # invalidation belongs to the preparation checks, not this persistence protocol.
    monkeypatch.setattr(
        peri_scribe.preparation,
        "runtime_fingerprint",
        lambda: "formal-journal-persistence",
    )
    monkeypatch.setattr(
        peri_scribe.kml.builder,
        "write_kmz_document",
        lambda _fires, _name, stream, **_kwargs: stream.write(
            f'<kml generation="{scenario.generation}"/>',
        ),
    )
    original = peri_scribe.fire_updates.prepare_updates_for_state

    def prepare(
        directory: pathlib.Path,
        fires: list[peri_scribe.kml.fire_data.FireGeometry],
        scores: peri_scribe.models.FireScores,
        *,
        previous: peri_scribe.fire_updates.State,
    ) -> peri_scribe.fire_updates.PreparedUpdates:
        """Observe prepared payloads without replacing recovery or identity logic.

        Args:
            directory: The year directory.
            fires: The fixture's real fire geometry records.
            scores: Current score input.
            previous: The validated checkpoint after production recovery.

        Returns:
            The unchanged result of actual preparation.
        """
        result = original(directory, fires, scores, previous=previous)
        scenario.observe_preparation(result)
        return result

    monkeypatch.setattr(peri_scribe.fire_updates, "prepare_updates_for_state", prepare)


def build(scenario: Scenario, now: datetime.datetime, *, fresh: bool) -> None:
    """Call the real builder with one stable input generation and clock.

    Args:
        scenario: The fixture's current generation.
        now: Wall-clock time for completion and monthly rotation.
        fresh: Whether a new publication inventory accompanies this KMZ.
    """
    if (
        now >= tests.formal.helpers.journal.EPOCH + datetime.timedelta(days=60)
        and not scenario.aged
    ):
        scenario.event("age")
        scenario.aged = True
    publish_fixture(scenario, now, fresh=fresh)


def publish_fixture(
    scenario: tests.formal.helpers.journal_wire_observer.Scenario,
    now: datetime.datetime,
    *,
    fresh: bool,
) -> None:
    """Publish one fixture generation through the full builder.

    Args:
        scenario: The fixture's current generation.
        now: The time of publication and log rotation.
        fresh: Whether to supply a new source inventory.
    """
    scenario.viewer_times[now] = scenario.generation
    inputs = scenario.collection()
    with time_machine.travel(now, tick=False):
        peri_scribe.kml.builder.create_kmz(
            scenario.directory,
            publication_inputs=inputs if fresh else None,
        )


def write_input_catalogue(path: pathlib.Path) -> None:
    """Capture exact inputs for first publication, a new batch, and its retry.

    Args:
        path: Private storage for the current hard-process fixture catalogue.
    """
    with tempfile.TemporaryDirectory(dir=path.parent) as scratch:
        catalogue = prepare_catalogue(pathlib.Path(scratch) / "2026")
    path.write_text(catalogue.model_dump_json(), encoding="utf-8")


type Preparation = tuple[
    int,
    peri_scribe.fire_updates.State,
    peri_scribe.fire_updates.PreparedUpdates,
]


def prepare_catalogue(
    directory: pathlib.Path,
) -> tests.formal.helpers.journal_builder_inputs.Catalogue:
    """Prepare the fixture's real inputs for every reachable checkpoint.

    Args:
        directory: Disposable year storage for full builder preparation.

    Returns:
        The prepared inputs for each matching generation and checkpoint.
    """
    prepared: list[Preparation] = []
    documents: list[str] = []
    image_sets: list[tuple[tuple[str, bytes], ...]] = []
    scenario = tests.formal.helpers.journal_wire_observer.Scenario(directory=directory)
    with tests.helpers.doubles.attribute_overrides.AttributeOverrides() as patch:
        install(patch, scenario)
        prepare = peri_scribe.fire_updates.prepare_updates_for_state
        decorate = peri_scribe.updates.with_previews

        def capture(
            directory: pathlib.Path,
            fires: list[peri_scribe.kml.fire_data.FireGeometry],
            scores: peri_scribe.models.FireScores,
            *,
            previous: peri_scribe.fire_updates.State,
        ) -> peri_scribe.fire_updates.PreparedUpdates:
            """Record the exact key and preparation returned by the full builder.

            Args:
                directory: The builder's disposable year directory.
                fires: The fixture's current prepared geometry.
                scores: The scores supplied by the builder.
                previous: The actual acknowledged baseline after recovery.

            Returns:
                The original prepared batch and next checkpoint.
            """
            result = prepare(directory, fires, scores, previous=previous)
            prepared.append((scenario.generation, previous, result))
            return result

        def confirm_viewer(
            snapshot: peri_scribe.updates.Snapshot,
            fires: list[peri_scribe.kml.fire_data.FireGeometry],
            cities: geopandas.GeoDataFrame,
            *,
            state: peri_scribe.fire_updates.State | None,
        ) -> peri_scribe.updates.Snapshot:
            """Check that viewer decoration preserves these recorded fields.

            Args:
                snapshot: The native viewer fold over the actual update log.
                fires: The fixture's current prepared geometry.
                cities: The current city layer available to presentation.
                state: The acknowledged mapping checkpoint.

            Returns:
                The snapshot decorated by the full builder.
            """
            result = decorate(snapshot, fires, cities, state=state)
            assert result.model_dump_json() == snapshot.model_dump_json()
            return result

        patch.setattr(peri_scribe.fire_updates, "prepare_updates_for_state", capture)
        patch.setattr(peri_scribe.updates, "with_previews", confirm_viewer)
        for seconds, generation in enumerate((1, 2, 2), start=1):
            scenario.generation = generation
            now = tests.formal.helpers.journal.EPOCH + datetime.timedelta(
                seconds=seconds,
            )
            with peri_scribe.pipeline_state.run_lock(scenario.directory) as acquired:
                assert acquired
                publish_fixture(scenario, now, fresh=True)
            with zipfile.ZipFile(
                peri_scribe.paths.kmz_path(scenario.directory),
            ) as archive:
                documents.append(archive.read("doc.kml").decode())
                image_sets.append(
                    tuple(
                        (member, archive.read(member))
                        for member in archive.namelist()
                        if member != "doc.kml"
                    ),
                )
    return validate_catalogue(prepared, documents, image_sets)


def validate_catalogue(
    prepared: list[Preparation],
    documents: list[str],
    image_sets: list[tuple[tuple[str, bytes], ...]],
) -> tests.formal.helpers.journal_builder_inputs.Catalogue:
    """Check checkpoint closure and preserve the exact round-tripped fixture inputs.

    Args:
        prepared: Real generation and checkpoint inputs with each prepared batch.
        documents: The actual KMZ document member of each generation and retry.
        image_sets: Ordered images published by each full build.

    Returns:
        Immutable inputs that can be selected in fresh persistence processes.
    """
    assert [len(updates.records) for _, _, updates in prepared] == [2, 2, 0]
    (_, empty, first), (_, first_state, second), (_, second_state, repeated) = prepared
    assert empty == peri_scribe.fire_updates.State()
    assert first_state == first.state
    assert second_state == repeated.state == second.state
    assert documents[1] == documents[2]
    assert image_sets[0] == image_sets[1] == image_sets[2]
    catalogue = tests.formal.helpers.journal_builder_inputs.Catalogue(
        entries=tuple(
            tests.formal.helpers.journal_builder_inputs.Entry(
                generation=generation,
                previous=previous.model_dump_json(),
                updates=tests.formal.helpers.journal_builder_inputs.PREPARED.dump_json(
                    updates,
                ).decode(),
            )
            for generation, previous, updates in prepared
        ),
        documents=tuple(documents[:2]),
        images=image_sets[0],
    )
    content = catalogue.model_dump_json()
    decoded = tests.formal.helpers.journal_builder_inputs.Catalogue.model_validate_json(
        content,
    )
    assert decoded == catalogue
    for generation, previous, updates in prepared:
        assert decoded.prepare(generation, previous) == updates
    return catalogue


def initial_publication(scenario: Scenario, *, fresh: bool) -> None:
    """Record the first publication and start the next batch of the same history.

    Args:
        scenario: The concrete year and model path for one exact pair of modes.
        fresh: Whether the first publication receives current source inputs.
    """
    pytest = importlib.import_module("pytest")
    with pytest.MonkeyPatch.context() as monkeypatch, structlog.testing.capture_logs():
        install(monkeypatch, scenario)
        tests.formal.helpers.journal_wire_observer.boundary(
            monkeypatch,
            scenario.inspect,
            None,
        )
        build(
            scenario,
            tests.formal.helpers.journal.EPOCH + datetime.timedelta(seconds=1),
            fresh=fresh,
        )
    scenario.event("batch")
    scenario.generation = 2


def interrupt_before_rotation(scenario: Scenario, *, fresh: bool) -> None:
    """Leave the second journal on disk for recovery across a later month.

    Args:
        scenario: A private continuation of the completed first publication.
        fresh: Whether the interrupted build receives current source inputs.
    """
    pytest = importlib.import_module("pytest")
    with pytest.MonkeyPatch.context() as monkeypatch, structlog.testing.capture_logs():
        install(monkeypatch, scenario)
        tests.formal.helpers.journal_wire_observer.boundary(
            monkeypatch,
            scenario.inspect,
            peri_scribe.fire_updates.pending_path(scenario.directory),
        )
        with pytest.raises(tests.formal.helpers.journal_wire_observer.ProcessLoss):
            build(
                scenario,
                tests.formal.helpers.journal.EPOCH + datetime.timedelta(seconds=2),
                fresh=fresh,
            )
    scenario.event("crash")


def replay(
    scenario: Scenario,
    destination: str,
    *,
    after: bool,
    fresh: bool,
) -> None:
    """Check process loss, recovery, and final viewer contents from a checked prefix.

    Args:
        scenario: The exact prior files and TLC path for this interruption.
        destination: One registered durable file boundary or rotation operation.
        after: Whether to fail after the selected mutation.
        fresh: Whether the builder receives fresh publication inputs.
    """
    epoch = tests.formal.helpers.journal.EPOCH
    directory = scenario.directory
    log = directory / "logs" / tests.formal.helpers.journal.LOG_NAME
    targets = {
        "kmz": peri_scribe.paths.kmz_path(directory),
        "publication": peri_scribe.publication.publication_path(directory),
        "journal": peri_scribe.fire_updates.pending_path(directory),
        "append": log,
        "checkpoint": peri_scribe.fire_updates.state_path(directory),
        "unlink journal": peri_scribe.fire_updates.pending_path(directory),
        "viewer": directory / "maps" / "updates.json",
        "archive": log.with_suffix(".jsonl.zst"),
        "unlink plain": log,
    }
    rotation = destination in ROTATION_DESTINATIONS
    # Process-loss diagnostics can stay structured while this fixture checks files.
    pytest = importlib.import_module("pytest")
    with pytest.MonkeyPatch.context() as monkeypatch, structlog.testing.capture_logs():
        install(monkeypatch, scenario)
        now = epoch + datetime.timedelta(days=60 if rotation else 0, seconds=3)
        with pytest.MonkeyPatch.context() as failure:
            tests.formal.helpers.journal_wire_observer.boundary(
                failure,
                scenario.inspect,
                targets[destination],
                unlink=destination.startswith("unlink"),
                after=after,
            )
            with pytest.raises(tests.formal.helpers.journal_wire_observer.ProcessLoss):
                build(scenario, now, fresh=fresh)
        scenario.event("crash")
        with pytest.MonkeyPatch.context() as observer:
            tests.formal.helpers.journal_wire_observer.boundary(
                observer,
                scenario.inspect,
                None,
            )
            build(scenario, now + datetime.timedelta(seconds=1), fresh=fresh)
            build(scenario, now + datetime.timedelta(seconds=2), fresh=fresh)
        scenario.inspect()
    assert scenario.checks > MINIMUM_OBSERVATIONS
    assert not peri_scribe.fire_updates.pending_path(directory).exists()
    assert (
        scenario.number(
            peri_scribe.publication.read_state(
                peri_scribe.fire_updates.state_path(directory),
                peri_scribe.fire_updates.State,
            ),
        )
        == GENERATION_COUNT
    )
    entries = peri_scribe.updates.read_entries(directory)
    assert len(entries) == GENERATION_COUNT * RECORDS_PER_GENERATION
    assert {int(entry.mapped_area.value) for entry in entries} == {100, 101, 200, 201}
    snapshot = json.loads((directory / "maps" / "updates.json").read_text())
    assert len(snapshot["updates"]) == (0 if rotation else 4)
    publication = peri_scribe.publication.read_publication(
        directory,
        peri_scribe.paths.kmz_path(directory),
    )
    assert (publication is not None) == fresh
