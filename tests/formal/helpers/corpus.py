"""Share only complete checked model data within one isolated pytest run."""

import collections.abc
import fcntl
import functools
import pathlib
import tempfile

import pydantic

import tests.formal.helpers.tlc


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
    return load(
        directory,
        f"graph-{module}-{config}",
        pydantic.TypeAdapter(tests.formal.helpers.tlc.Graph),
        functools.partial(tests.formal.helpers.tlc.graph, module, config),
    )


def states(module: str, config: str, directory: pathlib.Path) -> list[dict[str, str]]:
    """Keep state-only checks tied to one complete exploration in this run.

    Args:
        module: The TLA+ module name.
        config: Its registered finite configuration.
        directory: The current pytest run's shared model storage.

    Returns:
        Every checked state with its raw TLC field values.
    """
    return load(
        directory,
        f"states-{module}-{config}",
        pydantic.TypeAdapter(list[dict[str, str]]),
        functools.partial(tests.formal.helpers.tlc.states, module, config),
    )
