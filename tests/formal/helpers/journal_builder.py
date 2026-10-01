"""Exercise builder crash boundaries while retaining the real persistence stack."""

import collections
import compression.zstd
import dataclasses
import datetime
import json
import pathlib
import re
import zipfile

import geopandas
import pytest
import time_machine

import peri_scribe.fire_updates
import peri_scribe.fires.derived_layers
import peri_scribe.fires.index
import peri_scribe.fires.score_files
import peri_scribe.kml.builder
import peri_scribe.kml.fire_data
import peri_scribe.models
import peri_scribe.paths
import peri_scribe.publication
import peri_scribe.report.gathering
import peri_scribe.updates
import tests.formal.helpers.journal
import tests.formal.helpers.paths
import tests.formal.helpers.tlc
import tests.helpers.factories.peri_scribe.fire_updates
from measurement_units import units


type Projection = tuple[int, int, int, int, int, tuple[int, ...], tuple[int, ...], bool]
GENERATION_COUNT = 2
RECORDS_PER_GENERATION = 2
MINIMUM_OBSERVATIONS = 20


class ProcessLoss(BaseException):
    """Interrupt the caller outside ordinary exception handlers."""


def projections(
    directory: pathlib.Path,
) -> dict[tuple[bool, ...], tests.formal.helpers.paths.Contract[Projection]]:
    """Project every checked nonempty-batch state to observable file generations.

    Args:
        directory: An isolated TLC export directory.

    Returns:
        Directed execution contracts, separated by exact publication modes.
    """
    graph = tests.formal.helpers.tlc.graph(
        "UpdateJournal",
        "UpdateJournal",
        directory,
    )
    return contracts(graph)


def contracts(
    graph: tests.formal.helpers.tlc.Graph,
) -> dict[tuple[bool, ...], tests.formal.helpers.paths.Contract[Projection]]:
    """Retain exact publication modes while reusing one complete checked graph.

    Args:
        graph: The complete UpdateJournal graph exported by a successful TLC run.

    Returns:
        Directed execution contracts separated by exact publication modes.
    """
    allowed: dict[tuple[bool, ...], dict[int, Projection]] = collections.defaultdict(
        dict,
    )
    for identifier, fields in graph.states.items():
        if fields["hasRecords"] != "<<TRUE, TRUE>>":
            continue
        if "gated |-> TRUE" in fields["publicationModes"]:
            continue
        fresh_inputs = tuple(
            value == "TRUE"
            for value in re.findall(
                r"freshInputs \|-> (TRUE|FALSE)",
                fields["publicationModes"],
            )
        )
        scalars = dict(re.findall(r"(\w+) \|-> (\d+)", fields["durable"]))
        state = tests.formal.helpers.journal.durable(fields["durable"])
        allowed[fresh_inputs][identifier] = (
            int(scalars["kmz"]),
            int(scalars["publication"]),
            state.journal,
            state.checkpoint,
            int(scalars["viewer"]),
            state.plain,
            state.archive,
            "rotationReceipt |-> TRUE" in fields["durable"],
        )
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
class Scenario:
    """Retain real states and timestamps while abstracting expensive input rendering."""

    directory: pathlib.Path
    allowed: tests.formal.helpers.paths.Contract[Projection] | None = dataclasses.field(
        repr=False,
    )
    execution: tests.formal.helpers.paths.Path[Projection] | None = None
    aged: bool = False
    generation: int = 1
    states: dict[int, peri_scribe.fire_updates.State] = dataclasses.field(
        default_factory=dict,
    )
    timestamps: dict[int, datetime.datetime] = dataclasses.field(default_factory=dict)
    batch_ids: dict[int, str] = dataclasses.field(default_factory=dict)
    viewer_times: dict[datetime.datetime, int] = dataclasses.field(default_factory=dict)
    checks: int = 0

    def geometries(self) -> list[peri_scribe.kml.fire_data.FireGeometry]:
        """Provide two independently logged fires for the current generation.

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
                        + datetime.timedelta(seconds=self.generation),
                        area=(100 * self.generation + number) * units.acres,
                    ),
                ),
            )
            for number in range(2)
        ]

    def number(self, state: peri_scribe.fire_updates.State | None) -> int:
        """Recognize checkpoint contents by the actual prepared state payload.

        Args:
            state: The deserialized pending or acknowledged checkpoint.

        Returns:
            Its prepared generation, or zero when absent.
        """
        if state is None:
            return 0
        return next(number for number, value in self.states.items() if value == state)

    def log_counts(self, *, compressed: bool) -> tuple[int, ...]:
        """Validate record pairs and timestamp retention while reading actual logs.

        Args:
            compressed: Whether to project archive copies or plain copies.

        Returns:
            Physical batch counts for each generation in the model.
        """
        grouped: dict[int, list[peri_scribe.updates.LogEntry]] = (
            collections.defaultdict(
                list,
            )
        )
        pattern = "*-fire-updates.jsonl.zst" if compressed else "*-fire-updates.jsonl"
        opener = compression.zstd.open if compressed else open
        for path in (self.directory / "logs").glob(pattern):
            with opener(path, "rt", encoding="utf-8") as stream:
                for line in stream:
                    entry = peri_scribe.updates.LogEntry.model_validate_json(line)
                    generation = int(entry.mapped_area.value) // 100
                    assert entry.timestamp == self.timestamps[generation]
                    grouped[generation].append(entry)
        result = []
        for generation in (1, 2):
            entries = grouped[generation]
            assert len(entries) in {0, RECORDS_PER_GENERATION}
            if entries:
                assert {entry.identifier for entry in entries} == {"fire-0", "fire-1"}
                assert len({entry.batch_id for entry in entries}) == 1
            result.append(len(entries) // 2)
        return tuple(result)

    def snapshot(self) -> Projection:
        """Decode independently durable files without inventing abstract transitions.

        Returns:
            The real artifact generations, log multiplicities, and receipt presence.
        """
        pending = peri_scribe.publication.read_state(
            peri_scribe.fire_updates.pending_path(self.directory),
            peri_scribe.fire_updates.PendingUpdates,
        )
        journal = self.number(pending.state) if pending is not None else 0
        if pending is not None:
            self.timestamps.setdefault(journal, pending.timestamp)
            assert pending.timestamp == self.timestamps[journal]
            self.batch_ids.setdefault(journal, pending.batch_id)
            assert pending.batch_id == self.batch_ids[journal]
        checkpoint = self.number(
            peri_scribe.publication.read_state(
                peri_scribe.fire_updates.state_path(self.directory),
                peri_scribe.fire_updates.State,
            ),
        )
        kmz = 0
        path = peri_scribe.paths.kmz_path(self.directory)
        if path.exists():
            with zipfile.ZipFile(path) as archive:
                kmz = int(archive.read("doc.kml").decode().split('"')[1])
        publication = peri_scribe.publication.read_state(
            peri_scribe.publication.publication_path(self.directory),
            peri_scribe.publication.Publication,
        )
        published = int(next(iter(publication.files))) if publication is not None else 0
        viewer = peri_scribe.publication.read_state(
            self.directory / "maps" / "updates.json",
            peri_scribe.updates.Snapshot,
        )
        displayed = self.viewer_times[viewer.generated_at] if viewer is not None else 0
        if viewer is not None:
            # Imagery is outside the persistence model; every logged field stays exact.
            occurrences = tuple(
                record.model_copy(update={"preview": None}) for record in viewer.updates
            )
            assert occurrences == self.viewer_records(displayed, viewer.generated_at)
        return (
            kmz,
            published,
            journal,
            checkpoint,
            displayed,
            self.log_counts(compressed=False),
            self.log_counts(compressed=True),
            any((self.directory / "logs").glob("*.jsonl.rotation.json")),
        )

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
        """Keep actual crashes, collection generations, and clock changes in the path.

        Args:
            name: The concrete environment event between filesystem observations.
        """
        assert self.execution is not None
        self.execution = self.execution.event(
            name,
            terminal_phases=frozenset({'"done"'}) if name == "crash" else frozenset(),
        )

    def viewer_records(
        self,
        generation: int,
        now: datetime.datetime,
    ) -> tuple[peri_scribe.updates.Update, ...]:
        """Specify complete viewer payloads independently of the production fold.

        Args:
            generation: The mapping checkpoint at this viewer's publication.
            now: Its recorded generation time, separate from later retries.

        Returns:
            The visible fixture batches with each fire's prior acreage and identity.
        """
        return tuple(
            peri_scribe.updates.Update(
                timestamp=self.timestamps[batch],
                identifier=f"fire-{number}",
                log_identity=("id", f"fire-{number}"),
                history_identity=("id", f"fire-{number}"),
                name=f"Fire {number}",
                location=None,
                batch_id=self.batch_ids[batch],
                mapped_area=peri_scribe.updates.Acreage(value=100 * batch + number),
                previous_mapped_area=(
                    peri_scribe.updates.Acreage(value=100 * (batch - 1) + number)
                    if batch > 1
                    else None
                ),
            )
            for batch in range(1, generation + 1)
            if now - datetime.timedelta(hours=48) < self.timestamps[batch] <= now
            for number in range(RECORDS_PER_GENERATION)
        )


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


def install(monkeypatch: pytest.MonkeyPatch, scenario: Scenario) -> None:
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
        lambda *_args, **_kwargs: scenario.geometries(),
    )
    monkeypatch.setattr(
        peri_scribe.publication,
        "published_fires",
        lambda *_args, **_kwargs: {},
    )
    monkeypatch.setattr(peri_scribe.report.gathering, "report_from_fires", report)
    monkeypatch.setattr(
        peri_scribe.kml.builder,
        "write_kmz_document",
        lambda _fires, _name, stream, **_kwargs: stream.write(
            f'<kml generation="{scenario.generation}"/>',
        ),
    )
    original = peri_scribe.fire_updates.prepare_updates

    def prepare(
        directory: pathlib.Path,
        fires: list[peri_scribe.kml.fire_data.FireGeometry],
        scores: peri_scribe.models.FireScores,
    ) -> peri_scribe.fire_updates.PreparedUpdates:
        """Observe prepared payloads without replacing recovery or identity logic.

        Args:
            directory: The year directory.
            fires: The fixture's real fire geometry records.
            scores: Current score input.

        Returns:
            The unchanged result of actual preparation.
        """
        result = original(directory, fires, scores)
        assert not peri_scribe.fire_updates.pending_path(directory).exists()
        scenario.states[scenario.generation] = result.state
        return result

    monkeypatch.setattr(peri_scribe.fire_updates, "prepare_updates", prepare)


def boundary(
    monkeypatch: pytest.MonkeyPatch,
    scenario: Scenario,
    target: pathlib.Path | None,
    *,
    unlink: bool = False,
    after: bool = True,
) -> None:
    """Interrupt before or after one actual atomic replacement or deletion.

    Args:
        monkeypatch: Scoped replacement of filesystem methods.
        scenario: Actual directory and allowed model projections.
        target: Exact destination at which to interrupt, or None to observe only.
        unlink: Whether the selected boundary is a deletion.
        after: Whether the selected file mutation succeeds before process loss.
    """
    original_replace = pathlib.Path.replace
    original_unlink = pathlib.Path.unlink

    def replace(path: pathlib.Path, destination: pathlib.Path) -> pathlib.Path:
        """Preserve the real atomic replacement and inspect both sides.

        Args:
            path: Temporary file being published.
            destination: Public destination path.

        Returns:
            The destination returned by pathlib.

        Raises:
            ProcessLoss: At the selected interruption boundary.
        """
        scenario.inspect()
        if destination == target and not unlink and not after:
            raise ProcessLoss
        result = original_replace(path, destination)
        scenario.inspect()
        if destination == target and not unlink and after:
            raise ProcessLoss
        return result

    def remove(path: pathlib.Path, *, missing_ok: bool = False) -> None:
        """Keep archive and journal cleanup visible as separate durable actions.

        Args:
            path: File being removed.
            missing_ok: Whether absence is accepted by the real caller.

        Raises:
            ProcessLoss: At the selected interruption boundary.
        """
        scenario.inspect()
        if path == target and unlink and not after:
            raise ProcessLoss
        original_unlink(path, missing_ok=missing_ok)
        scenario.inspect()
        if path == target and unlink and after:
            raise ProcessLoss

    monkeypatch.setattr(pathlib.Path, "replace", replace)
    monkeypatch.setattr(pathlib.Path, "unlink", remove)


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
    scenario.viewer_times[now] = scenario.generation
    inputs = peri_scribe.publication.Collection(
        files={
            str(scenario.generation): peri_scribe.publication.FileStamp(
                size=scenario.generation,
                modified_nanoseconds=scenario.generation,
            ),
        },
    )
    with time_machine.travel(now, tick=False):
        peri_scribe.kml.builder.create_kmz(
            scenario.directory,
            publication_inputs=inputs if fresh else None,
        )


def replay(
    scenario: Scenario,
    destination: str,
    *,
    after: bool,
    fresh: bool,
    prior_fresh: bool,
) -> None:
    """Check builder prefixes, process loss, recovery, and final viewer contents.

    Args:
        scenario: An isolated builder fixture with TLC's allowed durable prefixes.
        destination: One registered durable file boundary or rotation operation.
        after: Whether to fail after the selected mutation.
        fresh: Whether the builder receives fresh publication inputs.
        prior_fresh: Whether an older publication checkpoint already exists.
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
    rotation = destination in {"archive", "unlink plain"}
    with pytest.MonkeyPatch.context() as monkeypatch:
        install(monkeypatch, scenario)
        with pytest.MonkeyPatch.context() as observer:
            boundary(observer, scenario, None)
            build(scenario, epoch + datetime.timedelta(seconds=1), fresh=prior_fresh)
        scenario.event("batch")
        scenario.generation = 2
        if rotation:
            with pytest.MonkeyPatch.context() as first_failure:
                boundary(first_failure, scenario, targets["journal"])
                with pytest.raises(ProcessLoss):
                    build(scenario, epoch + datetime.timedelta(seconds=2), fresh=fresh)
            scenario.event("crash")
        now = epoch + datetime.timedelta(days=60 if rotation else 0, seconds=3)
        with pytest.MonkeyPatch.context() as failure:
            boundary(
                failure,
                scenario,
                targets[destination],
                unlink=destination.startswith("unlink"),
                after=after,
            )
            with pytest.raises(ProcessLoss):
                build(scenario, now, fresh=fresh)
        scenario.event("crash")
        with pytest.MonkeyPatch.context() as observer:
            boundary(observer, scenario, None)
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
