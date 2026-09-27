"""Check hard process termination and fresh recovery against the checked contracts."""

import collections.abc
import dataclasses
import itertools
import json
import pathlib
import signal
import sys

import peri_scribe.fire_updates
import peri_scribe.updates
import tests.formal.helpers.crash_worker
import tests.formal.helpers.journal_builder
import tests.formal.helpers.log_rotation
import tests.formal.helpers.oracle
import tests.formal.helpers.paths
import tests.formal.helpers.pipeline_state
import tests.formal.helpers.process
import tests.formal.helpers.product_cache
import tests.formal.helpers.tlc


type Marker = tuple[int, bool, bool, bool]
PROCESS_PHASES = ("seed", "crash", "recover")

MARKER_FAULTS = tuple(
    (boundary, after, method)
    for method, (boundary, after) in itertools.product(
        ("exit", "kill"),
        (("marker", False), ("marker", True), ("fire", True), ("evacuations", True)),
    )
)
BUILDER_FAULTS = tuple(
    (boundary, after, "exit" if after else "kill")
    for boundary, after in itertools.product(
        (
            "kmz",
            "publication",
            "journal",
            "append",
            "checkpoint",
            "unlink journal",
            "viewer",
        ),
        (False, True),
    )
)
ROTATION_FAULTS = tuple(
    (boundary, after, "kill" if after else "exit")
    for boundary, after in itertools.product(
        ("receipt", "archive", "source", "retire"),
        (False, True),
    )
)
CACHE_BOUNDARIES = (
    "NEW_PAYLOAD",
    "SHARED_PAYLOAD",
    "MANIFEST",
    "PRUNE",
    "commit",
    "commit",
)


def invoke(request: tests.formal.helpers.crash_worker.Request) -> None:
    """Reject ordinary failures and missing fault injection as evidence of a crash.

    Args:
        request: One seed, crash, or fresh recovery subprocess.
    """
    result = tests.formal.helpers.process.run(
        [sys.executable, "-m", "tests.formal.helpers.crash_worker"],
        standard_input=json.dumps(dataclasses.asdict(request)),
        cwd=tests.formal.helpers.oracle.DIRECTORY.parents[1],
        timeout=30,
    )
    expected = (
        tests.formal.helpers.crash_worker.EXIT_STATUS
        if request.method == "exit"
        else -signal.SIGKILL
    )
    assert result.returncode == (expected if request.phase == "crash" else 0), (
        request,
        result.stdout,
        result.stderr,
    )
    if request.phase == "crash":
        root = pathlib.Path(request.root)
        assert not (root / "finally-ran").exists()
        assert not (root / "atexit-ran").exists()


def history(
    request: tests.formal.helpers.crash_worker.Request,
) -> list[dict[str, object]]:
    """Run three independent interpreter lifetimes over the same private files.

    Args:
        request: Family, exact fault boundary, and selected termination method.

    Returns:
        The complete observations across seeding, actual process death, and recovery.
    """
    for phase in PROCESS_PHASES:
        invoke(dataclasses.replace(request, phase=phase))
    records = [
        json.loads(line)
        for line in (pathlib.Path(request.root) / "trace.jsonl")
        .read_text()
        .splitlines()
    ]
    assert sum(record["kind"] == "crash" for record in records) == 1
    processes = [record["value"] for record in records if record["kind"] == "process"]
    assert len(set(processes)) == len(processes) == len(PROCESS_PHASES)
    return records


def frozen(value: object) -> collections.abc.Hashable:
    """Restore nested immutable observations from JSON without losing multiplicity.

    Args:
        value: A JSON-safe scalar or nested sequence emitted by a real writer.

    Returns:
        Its immutable tuple representation for comparison with TLC projections.
    """
    if isinstance(value, list):
        return tuple(frozen(item) for item in value)
    assert isinstance(value, collections.abc.Hashable)
    return value


def match[Value: collections.abc.Hashable](
    contract: tests.formal.helpers.paths.Contract[Value],
    records: list[dict[str, object]],
    *,
    crash: str,
    terminal_phases: frozenset[str] = frozenset(),
) -> tests.formal.helpers.paths.Path[Value]:
    """Fresh processes must extend the same pre-crash abstract execution.

    Args:
        contract: Real checked graph and its explicit observation projection.
        records: All observations, including the actual process-exit event.
        crash: The model's explicit crash category.
        terminal_phases: Fully completed phases where exit needs no recovery action.

    Returns:
        Every model state still compatible with the entire concrete execution.
    """
    path = None
    lookup: dict[collections.abc.Hashable, Value] = {
        value: value for value in contract.values.values()
    }
    for record in records:
        kind = record["kind"]
        if kind == "observe":
            observed = frozen(record["value"])
            assert observed in lookup, ("observation outside checked states", observed)
            value = lookup[observed]
            path = contract.start(value) if path is None else path.observe(value)
        elif kind in {"event", "crash"}:
            assert path is not None
            event = crash if kind == "crash" else str(record["value"])
            path = path.event(
                event,
                terminal_phases=terminal_phases if kind == "crash" else frozenset(),
            )
    assert path is not None
    return path


def builders(
    directory: pathlib.Path,
    contract: tests.formal.helpers.paths.Contract[
        tests.formal.helpers.journal_builder.Projection
    ],
    fault: tuple[str, bool, str],
) -> None:
    """Check every visible artifact around one selected hard builder interruption.

    Args:
        directory: Isolated subprocess storage for one three-process execution.
        contract: The checked graph restricted to fresh publication generations.
        fault: Artifact boundary, before/after placement, and termination method.
    """
    boundary, after, method = fault
    request = tests.formal.helpers.crash_worker.Request(
        root=str(directory),
        family="builder",
        phase="crash",
        boundary=boundary,
        after=after,
        method=method,
    )
    records = history(request)
    path = match(
        contract,
        records,
        crash="crash",
        terminal_phases=frozenset({'"done"'}),
    )
    assert any(
        contract.graph.states[node]["phase"] == '"done"' for node in path.candidates
    )
    assert not peri_scribe.fire_updates.pending_path(request.directory).exists()
    entries = peri_scribe.updates.read_entries(request.directory)
    assert sorted(int(entry.mapped_area.value) for entry in entries) == [
        100,
        101,
        200,
        201,
    ]
    assert (
        len({entry.batch_id for entry in entries})
        == tests.formal.helpers.journal_builder.GENERATION_COUNT
    )


def rotations(
    directory: pathlib.Path,
    contract: tests.formal.helpers.paths.Contract[
        tests.formal.helpers.log_rotation.Projection
    ],
    fault: tuple[str, bool, str],
) -> None:
    """Real process death cannot repeat archived diagnostic occurrences on restart.

    Args:
        directory: Private subprocess storage for one crash boundary.
        contract: The checked log receipt and publication state graph.
        fault: File boundary, before/after placement, and termination method.
    """
    boundary, after, method = fault
    request = tests.formal.helpers.crash_worker.Request(
        root=str(directory),
        family="rotation",
        phase="crash",
        boundary=boundary,
        after=after,
        method=method,
    )
    path = match(
        contract,
        history(request),
        crash="Crash",
        terminal_phases=frozenset({'"idle"'}),
    )
    assert path.value == ((), (2, 1, 1), False, (), (), ())


def marker_contract(
    graph: tests.formal.helpers.tlc.Graph,
) -> tests.formal.helpers.paths.Contract[Marker]:
    """Exclude unperformed derived stages from the fetch-only trace contract.

    Args:
        graph: The complete checked FetchCrash graph.

    Returns:
        Actual FetchCrash successors with explicit process loss and retry transitions.
    """
    values = {}
    for identifier, state in graph.states.items():
        if (
            state["targets"] != "<<1, 1>>"
            or state["unconditional"] != "FALSE"
            or state["full"] != "FALSE"
        ):
            continue
        pending = tests.formal.helpers.pipeline_state.state(state["pending"])
        sources = tests.formal.helpers.log_rotation.numbers(state["source"])
        values[identifier] = (
            tests.formal.helpers.pipeline_state.mask(pending.remaining),
            pending.unconditional,
            bool(sources[0]),
            bool(sources[1]),
        )
    actions = {
        edge: (
            "crash"
            if graph.states[edge.source]["crashes"]
            != graph.states[edge.target]["crashes"]
            else "derive"
            if graph.states[edge.target]["action"] == '"derive"'
            else "step"
        )
        for edges in graph.outgoing.values()
        for edge in edges
    }
    return tests.formal.helpers.paths.Contract(
        graph=graph,
        values=values,
        actions=actions,
        internal=frozenset({"step"}),
    )


def markers(
    directory: pathlib.Path,
    contract: tests.formal.helpers.paths.Contract[Marker],
    fault: tuple[str, bool, str],
) -> None:
    """A killed source writer leaves durable obligations for the unchanged retry.

    Args:
        directory: Isolated subprocess storage for one three-process execution.
        contract: The checked fetch-recovery state graph.
        fault: Source or marker boundary, before/after placement, and exit method.
    """
    boundary, after, method = fault
    request = tests.formal.helpers.crash_worker.Request(
        root=str(directory),
        family="marker",
        phase="crash",
        boundary=boundary,
        after=after,
        method=method,
    )
    path = match(contract, history(request), crash="crash")
    assert path.value == (15, True, True, True)
    assert any(
        contract.graph.states[node]["phase"] == '"derive"' for node in path.candidates
    )


def caches(
    directory: pathlib.Path,
    prefixes: dict[tuple[int, ...], dict[str, str]],
    index: int,
) -> None:
    """SQLite must discard killed uncommitted generations without Python rollback.

    Args:
        directory: Private database files for each process lifetime.
        prefixes: Complete checked statement traces and their durable outcomes.
        index: One statement or before/after commit boundary in the crash matrix.
    """
    boundary = CACHE_BOUNDARIES[index]
    committed = index == len(CACHE_BOUNDARIES) - 1
    request = tests.formal.helpers.crash_worker.Request(
        root=str(directory),
        family="cache",
        phase="crash",
        boundary=boundary,
        after=committed if boundary == "commit" else True,
        method="exit" if index % 2 else "kill",
    )
    records = history(request)
    prefix = (1, 2, 3, 4, 5)[: min(index + 2, 5)]
    pending = [
        frozen(record["value"]) for record in records if record["kind"] == "pending"
    ]
    for length, actual in enumerate(pending, start=2):
        expected = tests.formal.helpers.product_cache.expected_state(
            prefixes[prefix[:length]]["pending"],
        )
        assert actual == (expected[0], tuple(sorted(expected[1])))
    outcome = prefixes[*prefix, 7] if committed else prefixes[*prefix, 8]
    expected = tests.formal.helpers.product_cache.expected_state(outcome["durable"])
    recovered = [record["value"] for record in records if record["kind"] == "recovered"]
    assert frozen(recovered) == ((expected[0], tuple(sorted(expected[1]))),)
    rows = [record["value"] for record in records if record["kind"] == "rows"]
    assert rows == [tests.formal.helpers.product_cache.groups(expected[0])]
