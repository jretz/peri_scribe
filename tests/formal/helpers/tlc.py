"""Export checked TLC states so conformance exercises the actual specifications."""

import asyncio
import collections
import dataclasses
import json
import os
import pathlib
import re
import shutil
import tempfile

import tests.formal.helpers.oracle
import tests.formal.helpers.process
import tests.formal.helpers.tlc_worker


JAVA_OPTIONS = tests.formal.helpers.tlc_worker.JAVA_OPTIONS


@dataclasses.dataclass(frozen=True, kw_only=True)
class Edge:
    """Retain the actual successor relation, including TLC's action names."""

    source: int
    target: int
    action: str


@dataclasses.dataclass(frozen=True, kw_only=True)
class Graph:
    """Keep initial states distinct from states reachable only after prior actions."""

    states: dict[int, dict[str, str]]
    initial: frozenset[int]
    outgoing: dict[int, tuple[Edge, ...]]


@dataclasses.dataclass(frozen=True, kw_only=True)
class CheckedGraph:
    """Retain successful checker diagnostics with the complete exported graph."""

    graph: Graph
    output: str


@dataclasses.dataclass(frozen=True, kw_only=True)
class CheckedStates:
    """Retain an ordered valuation inventory and its successful checker diagnostics."""

    states: list[dict[str, str]]
    output: str


GRAPH_RECORD = re.compile(r"(-?\d+) (->|\[)")
EDGE_HEADER = re.compile(r' (-?\d+) \[label=(?=")')
STATE_HEADER = re.compile(r"^State (\d+):\n", re.MULTILINE)
TEMPORAL_CHECK = re.compile(
    r"^Checking (?:\d+ branches of )?temporal properties for the complete state space"
    r"\b",
    re.MULTILINE,
)


async def explore_async(
    module: str,
    config: str,
    directory: pathlib.Path,
    *,
    graph: bool = False,
    source_directory: pathlib.Path | None = None,
) -> tuple[str, str]:
    """Require complete successful exploration before exposing either dump format.

    Args:
        module: The model's module name.
        config: The registered finite configuration.
        directory: Private dump, TLC metadata, and JVM temporary storage.
        graph: Whether actual successor edges and initial-state marks are required.
        source_directory: Explicit TLC sources for an isolated fallback.

    Returns:
        The complete dump and successful checker output.
    """
    await asyncio.to_thread(directory.mkdir, parents=True, exist_ok=True)
    dump = directory / ("graph.dot" if graph else "states.dump")
    with tempfile.TemporaryDirectory(
        prefix="java-",
        dir=await asyncio.to_thread(directory.resolve),
    ) as java_directory:
        arguments = [
            "-workers",
            "1",
            "-lncheck",
            "final",
            "-seed",
            "1",
            "-metadir",
            str(directory / "metadata"),
            "-dump",
            *(["dot,actionlabels"] if graph else []),
            str(dump),
            "-config",
            f"{config}.cfg",
            f"{module}.tla",
        ]
        java = shutil.which("java")
        assert java is not None, "Run mise formal-conformance to provide Java"
        result = await tests.formal.helpers.process.execute(
            [
                java,
                *JAVA_OPTIONS,
                f"-Djava.io.tmpdir={java_directory}",
                "-cp",
                os.environ["PERI_SCRIBE_TLA_JAR"],
                "tlc2.TLC",
                *arguments,
            ],
            standard_input="",
            cwd=source_directory or tests.formal.helpers.oracle.DIRECTORY / "tla",
            maximum_seconds=180,
        )
    assert result.returncode == 0, result.stdout + result.stderr
    assert "Model checking completed. No error has been found." in result.stdout
    return dump.read_text(), result.stdout


def explore(
    module: str,
    config: str,
    directory: pathlib.Path,
    *,
    graph: bool = False,
) -> tuple[str, str]:
    """Keep synchronous consumers subject to the cancellable checker adapter.

    Args:
        module: The model's module name.
        config: The registered finite configuration.
        directory: Private checker storage.
        graph: Whether actual edges and initial marks are required.

    Returns:
        The complete dump and successful checker diagnostics.
    """
    return asyncio.run(explore_async(module, config, directory, graph=graph))


def fields(block: str) -> dict[str, str]:
    """Preserve raw TLC values without evaluating specification text.

    Args:
        block: One decoded state label.

    Returns:
        All variable values in that state.
    """
    assert block.startswith("/\\ "), ("unparsed TLC state label", block)
    parts = block.removeprefix("/\\ ").split("\n/\\ ")
    values = dict(part.split(" = ", 1) for part in parts)
    assert len(values) == len(parts), ("repeated TLC state field", block)
    assert all(name.isidentifier() and value for name, value in values.items()), (
        "unparsed TLC state field",
        block,
    )
    return values


def checked_count(output: str) -> int:
    """An empty or truncated state export cannot satisfy a conformance check.

    Args:
        output: Successful TLC diagnostics.

    Returns:
        TLC's distinct-state count.
    """
    counts = re.findall(r"([\d,]+) distinct states found", output)
    assert counts, output
    return int(counts[-1].replace(",", ""))


def graph(module: str, config: str, directory: pathlib.Path) -> Graph:
    """Export checked nodes, initial states, and directed edges in the same run.

    Args:
        module: The model's module name.
        config: The registered finite configuration.
        directory: Private TLC storage.

    Returns:
        The complete transition graph; no successors are inferred from projections.
    """
    dump, output = explore(module, config, directory, graph=True)
    return decode_graph(dump, output)


def decode_edge(
    line: str,
    source: int,
    start: int,
    decoder: json.JSONDecoder,
) -> Edge:
    """Read one ordered successor and decode its action as a quoted JSON string.

    Args:
        line: The complete DOT edge record.
        source: The signed fingerprint of its predecessor state.
        start: Offset following the edge arrow.
        decoder: The graph's JSON string decoder.

    Returns:
        The actual labeled successor from TLC.
    """
    header = EDGE_HEADER.match(line, start)
    assert header is not None, ("unparsed TLC edge", line)
    action, end = decoder.raw_decode(line, header.end())
    assert line.startswith(",", end), ("unparsed TLC edge", line)
    assert line.endswith("];"), ("unparsed TLC edge", line)
    return Edge(source=source, target=int(header[1]), action=action)


def decode_graph(dump: str, output: str) -> Graph:
    """Check state counts, edge endpoints, and reachability before sharing a graph.

    Args:
        dump: Complete TLC graph export.
        output: Diagnostics confirming the successful exploration and state counts.

    Returns:
        Every initial state, raw field, and actual successor edge.
    """
    nodes: dict[int, dict[str, str]] = {}
    initial: set[int] = set()
    outgoing: dict[int, list[Edge]] = {}
    decoder = json.JSONDecoder()
    for line in dump.splitlines():
        record = GRAPH_RECORD.match(line)
        if record is None:
            continue
        identifier = int(record[1])
        if record[2] == "->":
            # Liveness exports show implicit stuttering as an unlabeled dashed loop.
            # The matcher already permits stuttering on an unchanged observation.
            if line[record.end() :] == f' {identifier} [style="dashed"];':
                continue
            outgoing.setdefault(identifier, []).append(
                decode_edge(line, identifier, record.end(), decoder),
            )
        else:
            assert line.startswith('label="', record.end()), ("unparsed TLC node", line)
            assert line.endswith(("]", "];")), ("unparsed TLC node", line)
            label, end = decoder.raw_decode(line, record.end() + len("label="))
            assert identifier not in nodes, line
            # Only variable headers begin with this prefix. Wrapped values keep all
            # their remaining whitespace and delimiters.
            label = label.strip()
            assert label.startswith("/\\ "), ("unparsed TLC state label", label)
            blocks = label.removeprefix("/\\ ").split("\n/\\ ")
            nodes[identifier] = dict(block.split(" = ", 1) for block in blocks)
            if line.find("style = filled", end) >= 0:
                initial.add(identifier)
    assert len(nodes) == checked_count(output) > 0
    initial_count = re.search(
        r"initial states: (?:[\d,]+ states generated, with )?([\d,]+) "
        r"(?:distinct states?|of them distinct)",
        output,
    )
    assert initial_count is not None, output
    assert len(initial) == int(initial_count[1].replace(",", "")) > 0
    assert all(
        edge.source in nodes and edge.target in nodes
        for edges in outgoing.values()
        for edge in edges
    )
    reached = set(initial)
    remaining = list(initial)
    while remaining:
        for edge in outgoing.get(remaining.pop(), ()):
            if edge.target not in reached:
                reached.add(edge.target)
                remaining.append(edge.target)
    assert reached == set(nodes), "TLC graph omits reachability edges"
    assert dump.rstrip().endswith("}"), "incomplete TLC graph"
    return Graph(
        states=nodes,
        initial=frozenset(initial),
        outgoing={key: tuple(value) for key, value in outgoing.items()},
    )


async def checked_graph_async(
    module: str,
    config: str,
    directory: pathlib.Path,
    *,
    source_directory: pathlib.Path | None = None,
) -> CheckedGraph:
    """The model runner and conformance consumers use the same checked evidence.

    Args:
        module: The TLA+ module name.
        config: The exact finite configuration.
        directory: Private checker storage.
        source_directory: Explicit TLC sources for an isolated fallback.

    Returns:
        The complete graph and the successful exploration diagnostics.
    """
    dump, output = await explore_async(
        module,
        config,
        directory,
        graph=True,
        source_directory=source_directory,
    )
    return CheckedGraph(graph=decode_graph(dump, output), output=output)


def checked_graph(module: str, config: str, directory: pathlib.Path) -> CheckedGraph:
    """Synchronous fixtures publish the same artifact as the asynchronous runner.

    Args:
        module: The TLA+ module name.
        config: The exact finite configuration.
        directory: Private checker storage.

    Returns:
        The complete graph and the successful exploration diagnostics.
    """
    return asyncio.run(checked_graph_async(module, config, directory))


def decode_states(dump: str, output: str) -> list[dict[str, str]]:
    """Require the complete distinct-state inventory in its discovery order.

    Args:
        dump: The original numbered text export from TLC.
        output: Successful checker output with exploration and temporal diagnostics.

    Returns:
        Every distinct state's raw field values, in discovery order.
    """
    assert dump.endswith("\n\n"), "incomplete TLC state export"
    parts = STATE_HEADER.split(dump)
    assert not parts[0], "unparsed TLC state export header"
    count = checked_count(output)
    # The text writer emits one additional copy for each implicit liveness stutter.
    copies = 2 if TEMPORAL_CHECK.search(output) else 1
    labels: collections.Counter[str] = collections.Counter()
    for index, (number, block) in enumerate(
        zip(parts[1::2], parts[2::2], strict=True),
        1,
    ):
        assert number == str(index), "nonconsecutive TLC state numbers"
        labels[block.strip()] += 1
    assert len(labels) == count > 0, "TLC state count differs from the text export"
    assert all(value == copies for value in labels.values()), (
        "unexpected TLC state multiplicity"
    )
    return [fields(label) for label in labels]


async def checked_states_async(
    module: str,
    config: str,
    directory: pathlib.Path,
    *,
    source_directory: pathlib.Path | None = None,
) -> CheckedStates:
    """Export valuations from the same full checker run as the diagnostics.

    Args:
        module: The TLA+ module name.
        config: The exact finite configuration.
        directory: Private checker storage.
        source_directory: Explicit TLC sources for an isolated fallback.

    Returns:
        All checked valuations and the successful exploration diagnostics.
    """
    dump, output = await explore_async(
        module,
        config,
        directory,
        source_directory=source_directory,
    )
    return CheckedStates(states=decode_states(dump, output), output=output)


def checked_states(module: str, config: str, directory: pathlib.Path) -> CheckedStates:
    """Produce the state receipt when a conformance test starts a cold exploration.

    Args:
        module: The TLA+ module name.
        config: The exact finite configuration.
        directory: Private checker storage.

    Returns:
        All checked valuations and the successful exploration diagnostics.
    """
    return asyncio.run(checked_states_async(module, config, directory))


def states(
    module: str,
    config: str,
    directory: pathlib.Path,
) -> list[dict[str, str]]:
    """Reject incomplete exploration and preserve every exported variable verbatim.

    Args:
        module: The TLA+ module name without its suffix.
        config: The registered configuration name without its suffix.
        directory: An isolated location for this check's metadata and state dump.

    Returns:
        All distinct checked states, with raw TLC text keyed by variable name.
    """
    return checked_states(module, config, directory).states
