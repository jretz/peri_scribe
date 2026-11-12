"""Share only complete checked model data within one formal invocation.

Workers need the same successfully checked model. Partial output or evidence from an
earlier run cannot establish what the current specifications allow.

Design notes:
[Verification evidence and execution](../../../docs/algorithms/verification-tooling.md).
"""

import asyncio
import collections.abc
import fcntl
import functools
import pathlib
import tempfile

import pydantic

import tests.formal.helpers.model_registry
import tests.formal.helpers.session
import tests.formal.helpers.tlc
import tests.formal.helpers.tlc_frame_wire
import tests.formal.helpers.tlc_frames
import tests.formal.helpers.tlc_worker


def load[Value](
    directory: pathlib.Path,
    name: str,
    adapter: pydantic.TypeAdapter[Value],
    build: collections.abc.Callable[[pathlib.Path], Value],
) -> Value:
    """A failed or interrupted producer cannot publish reusable partial evidence.

    Args:
        directory: Storage shared by workers of this pytest run only.
        name: Unique identity of the model configuration and representation.
        adapter: Typed JSON encoding of the complete checked result.
        build: Producer that verifies its result before returning it.

    Returns:
        The verified result, generated once and shared with waiting workers.
    """
    directory.mkdir(parents=True, exist_ok=True)
    destination = directory / f"{name}.json"
    with (directory / f"{name}.lock").open("a+b") as lock:
        fcntl.flock(lock, fcntl.LOCK_EX)
        if not destination.exists():
            with tempfile.TemporaryDirectory(dir=directory) as temporary:
                staging = pathlib.Path(temporary)
                value = build(staging)
                published = staging / "complete.json"
                published.write_bytes(adapter.dump_json(value))
                published.replace(destination)
            return value
        contents = destination.read_bytes()
    return adapter.validate_json(contents)


def graph(
    module: str,
    config: str,
    directory: pathlib.Path,
) -> tests.formal.helpers.tlc.Graph:
    """Workers agree on one checked graph rather than independently chosen histories.

    Args:
        module: The TLA+ module name.
        config: Its registered finite configuration.
        directory: The current pytest run's shared model storage.

    Returns:
        Every checked state, initial mark, and actual successor edge.
    """
    require_graph(module, config)
    directory = tests.formal.helpers.session.directory() or directory
    framed = tests.formal.helpers.tlc_frames.path(directory, module, config)
    if framed is not None and framed.is_file():
        return tests.formal.helpers.tlc_frames.read(framed).graph()
    return load(
        directory,
        f"graph-{module}-{config}",
        pydantic.TypeAdapter(tests.formal.helpers.tlc.CheckedGraph),
        functools.partial(tests.formal.helpers.tlc.checked_graph, module, config),
    ).graph


def states(module: str, config: str, directory: pathlib.Path) -> list[dict[str, str]]:
    """Keep state-only checks tied to one complete exploration in this run.

    Args:
        module: The TLA+ module name.
        config: Its registered finite configuration.
        directory: The current pytest run's shared model storage.

    Returns:
        Every checked state with its raw TLC field values.
    """
    registry = tests.formal.helpers.model_registry
    if registry.exports().get((module, config)) is registry.Export.STATES:
        directory = tests.formal.helpers.session.directory() or directory
        framed = tests.formal.helpers.tlc_frames.path(directory, module, config)
        if framed is not None and framed.is_file():
            return tests.formal.helpers.tlc_frames.read(
                framed,
                with_edges=False,
            ).states()
        return load(
            directory,
            f"states-{module}-{config}",
            pydantic.TypeAdapter(tests.formal.helpers.tlc.CheckedStates),
            functools.partial(tests.formal.helpers.tlc.checked_states, module, config),
        ).states
    return list(graph(module, config, directory).states.values())


def projected_states(
    module: str,
    config: str,
    directory: pathlib.Path,
    names: tuple[str, ...],
    *,
    where: tuple[str, frozenset[str]],
) -> collections.abc.Iterator[dict[str, str]]:
    """Select exact raw fields from every matching state, in discovery order.

    Yields:
        Each matching row's selected fields, in discovery order.
    """
    evidence = tests.formal.helpers.session.directory() or directory
    framed = tests.formal.helpers.tlc_frames.path(evidence, module, config)
    if framed is not None and framed.is_file():
        receipt = tests.formal.helpers.tlc_frames.read(framed, with_edges=False)
        if isinstance(receipt, tests.formal.helpers.tlc_frame_wire.Receipt):
            yield from receipt.projected(names, where=where)
            return
        rows = receipt.states()
    else:
        rows = states(module, config, directory)
    field, accepted = where
    for row in rows:
        if row[field] in accepted:
            yield {name: row[name] for name in names}


def require_graph(module: str, config: str) -> None:
    """Reject a graph request when the registered evidence only contains states.

    Args:
        module: The model's module name.
        config: The registered finite configuration.

    Raises:
        ValueError: If this configuration supplies state evidence alone.
    """
    registry = tests.formal.helpers.model_registry
    if registry.exports().get((module, config)) is registry.Export.STATES:
        message = f"{module}/{config} exports checked states. A graph is required."
        raise ValueError(message)


async def load_async[Value](
    directory: pathlib.Path,
    name: str,
    adapter: pydantic.TypeAdapter[Value],
    build: collections.abc.Callable[[pathlib.Path], collections.abc.Awaitable[Value]],
) -> Value:
    """Waiting for another producer must remain cancellable.

    Args:
        directory: The outer formal invocation's temporary storage.
        name: Unique identity of the model configuration and representation.
        adapter: Typed JSON encoding of the complete checked result.
        build: Producer that verifies its result before returning it.

    Returns:
        The verified result, generated once and shared with waiting workers.
    """
    await asyncio.to_thread(directory.mkdir, parents=True, exist_ok=True)
    destination = directory / f"{name}.json"
    with (directory / f"{name}.lock").open("a+b") as lock:
        while True:
            try:
                fcntl.flock(lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
                break
            except BlockingIOError:
                await asyncio.sleep(0.02)
        if destination.exists():
            return adapter.validate_json(destination.read_bytes())
        with tempfile.TemporaryDirectory(dir=directory) as temporary:
            staging = pathlib.Path(temporary)
            value = await build(staging)
            published = staging / "complete.json"
            published.write_bytes(adapter.dump_json(value))
            published.replace(destination)
            return value


async def checked_graph(
    module: str,
    config: str,
    directory: pathlib.Path,
    *,
    worker: tests.formal.helpers.tlc_worker.Worker | None = None,
    source_directory: pathlib.Path | None = None,
) -> tests.formal.helpers.tlc.CheckedGraph:
    """Publish the directed evidence required by path consumers.

    Args:
        module: The TLA+ module name.
        config: The exact finite configuration.
        directory: The outer formal invocation's temporary storage.
        worker: A leased JVM with no other active model.
        source_directory: Explicit TLC sources for an isolated fallback.

    Returns:
        The full checked graph and its original checker diagnostics.
    """
    require_graph(module, config)
    return await load_async(
        directory,
        f"graph-{module}-{config}",
        pydantic.TypeAdapter(tests.formal.helpers.tlc.CheckedGraph),
        functools.partial(
            tests.formal.helpers.tlc.checked_graph_async,
            module,
            config,
            worker=worker,
            source_directory=source_directory,
        ),
    )


async def checked_states(
    module: str,
    config: str,
    directory: pathlib.Path,
    *,
    worker: tests.formal.helpers.tlc_worker.Worker | None = None,
    source_directory: pathlib.Path | None = None,
) -> tests.formal.helpers.tlc.CheckedStates:
    """Publish every checked state in the state inventory's own receipt.

    Args:
        module: The TLA+ module name.
        config: The exact finite configuration.
        directory: The outer formal invocation's temporary storage.
        worker: A leased JVM with no other active model.
        source_directory: Explicit TLC sources for an isolated fallback.

    Returns:
        The ordered checked states and their original checker diagnostics.
    """
    return await load_async(
        directory,
        f"states-{module}-{config}",
        pydantic.TypeAdapter(tests.formal.helpers.tlc.CheckedStates),
        functools.partial(
            tests.formal.helpers.tlc.checked_states_async,
            module,
            config,
            worker=worker,
            source_directory=source_directory,
        ),
    )
