"""Export checked TLC states so conformance exercises the actual specifications."""

import asyncio
import dataclasses
import json
import os
import pathlib
import re
import shutil
import tempfile

import tests.formal.helpers.oracle
import tests.formal.helpers.process


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


async def explore_async(
    module: str,
    config: str,
    directory: pathlib.Path,
    *,
    graph: bool = False,
) -> tuple[str, str]:
    """Require complete successful exploration before exposing either dump format.

    Args:
        module: The model's module name.
        config: The registered finite configuration.
        directory: Private dump, TLC metadata, and JVM temporary storage.
        graph: Whether actual successor edges and initial-state marks are required.

    Returns:
        The complete dump and successful checker output.
    """
    java = shutil.which("java")
    assert java is not None, "Run mise formal-conformance to provide Java"
    await asyncio.to_thread(directory.mkdir, parents=True, exist_ok=True)
    dump = directory / ("graph.dot" if graph else "states.dump")
    with tempfile.TemporaryDirectory(
        prefix="java-",
        dir=await asyncio.to_thread(directory.resolve),
    ) as java_directory:
        result = await tests.formal.helpers.process.execute(
            [
                java,
                "-XX:+UseParallelGC",
                "-Xmx1g",
                f"-Djava.io.tmpdir={java_directory}",
                "-cp",
                os.environ["PERI_SCRIBE_TLA_JAR"],
                "tlc2.TLC",
                "-workers",
                "1",
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
            ],
            standard_input="",
            cwd=tests.formal.helpers.oracle.DIRECTORY / "tla",
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
    values = dict(
        re.findall(r"/\\ (\w+) = (.*?)(?=\n/\\|\Z)", block.strip(), re.DOTALL),
    )
    assert values, block
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


def decode_graph(dump: str, output: str) -> Graph:
    """Reject missing states or edges before a graph becomes reusable evidence.

    Args:
        dump: Complete TLC graph export.
        output: Diagnostics confirming the successful exploration and state counts.

    Returns:
        Every initial state, raw field, and actual successor edge.
    """
    quoted = r'"(?:\\.|[^"\\])*"'
    nodes: dict[int, dict[str, str]] = {}
    initial: set[int] = set()
    outgoing: dict[int, list[Edge]] = {}
    for line in dump.splitlines():
        node = re.fullmatch(rf"(-?\d+) \[label=({quoted})(.*)\];?", line)
        edge = re.fullmatch(
            rf"(-?\d+) -> (-?\d+) \[label=({quoted}),.*\];",
            line,
        )
        if re.match(r"-?\d+ ->", line):
            assert edge is not None, ("unparsed TLC edge", line)
        if re.match(r"-?\d+ \[", line):
            assert node is not None, ("unparsed TLC node", line)
        if node is not None:
            identifier = int(node[1])
            assert identifier not in nodes
            nodes[identifier] = fields(json.loads(node[2]))
            if "style = filled" in node[3]:
                initial.add(identifier)
        elif edge is not None:
            value = Edge(
                source=int(edge[1]),
                target=int(edge[2]),
                action=json.loads(edge[3]),
            )
            outgoing.setdefault(value.source, []).append(value)
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
) -> CheckedGraph:
    """The model runner and conformance consumers use the same checked evidence.

    Args:
        module: The TLA+ module name.
        config: The exact finite configuration.
        directory: Private checker storage.

    Returns:
        The complete graph and the successful exploration diagnostics.
    """
    dump, output = await explore_async(module, config, directory, graph=True)
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
    dump, output = explore(module, config, directory)
    records = [fields(block) for block in re.split(r"State \d+:\n", dump)[1:]]
    assert len(records) == checked_count(output) > 0
    return records
