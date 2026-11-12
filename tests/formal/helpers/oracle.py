"""Execute the compiled definitions whose properties Lean checks."""

import collections.abc
import functools
import pathlib

import tests.formal.helpers.process


DIRECTORY = pathlib.Path(__file__).resolve().parents[1]
SMALL_BATCH_COMMANDS = 64
SMALL_BATCH_CHARACTERS = 4096
type ExecutableIdentity = tuple[int, int, int, int, int]


def execute(
    path: pathlib.Path,
    commands: collections.abc.Sequence[str],
) -> tuple[tuple[int, ...], ...]:
    """Publish answers only after the compiled checker has returned every response.

    Args:
        path: The current Lake executable.
        commands: Complete requests in protocol order.

    Returns:
        Validated, immutable responses in request order.
    """
    result = tests.formal.helpers.process.run(
        [str(path)],
        standard_input="\n".join(commands) + "\n",
        can_start_nested_tools=False,
    )
    assert result.returncode == 0, result.stdout + result.stderr
    responses = tuple(
        tuple(map(int, line.split())) for line in result.stdout.splitlines()
    )
    assert len(responses) == len(commands), result.stderr
    return responses


@functools.lru_cache(maxsize=128)
def small_batch(
    path: pathlib.Path,
    identity: ExecutableIdentity,
    commands: tuple[str, ...],
) -> tuple[tuple[int, ...], ...]:
    """Share exact short requests to the same stateless executable in one worker.

    Args:
        path: The executable producing the answers.
        identity: File identity and timestamps qualifying the cached result.
        commands: The exact ordered request, including duplicate lines.

    Returns:
        The complete immutable response to that request.
    """
    return execute(path, commands)


def evaluate(
    commands: list[str],
    *,
    executable: str = "oracle",
) -> list[tuple[int, ...]]:
    """Keep Python expectations tied to the definitions compiled by Lean.

    Args:
        commands: Requests in the formal oracle's line protocol.
        executable: The Lake executable owning those checked definitions.

    Returns:
        One tuple of integer results for every request, in request order.
    """
    path = DIRECTORY / "lean" / ".lake" / "build" / "bin" / executable
    if (
        len(commands) > SMALL_BATCH_COMMANDS
        or sum(map(len, commands)) > SMALL_BATCH_CHARACTERS
    ):
        return list(execute(path, commands))
    status = path.stat()
    identity = (
        status.st_dev,
        status.st_ino,
        status.st_size,
        status.st_mtime_ns,
        status.st_ctime_ns,
    )
    return list(small_batch(path, identity, tuple(commands)))


def evaluate_distinct(
    commands: list[str],
    *,
    executable: str,
) -> list[tuple[int, ...]]:
    """Evaluate each exact request to a stateless oracle once per call.

    Args:
        commands: Complete requests whose answers depend only on their text.
        executable: The Lake executable owning those checked definitions.

    Returns:
        Every original response in order, including repeated responses.
    """
    if not commands:
        return []
    distinct = list(dict.fromkeys(commands))
    responses = evaluate(distinct, executable=executable)
    answers = dict(zip(distinct, responses, strict=True))
    return [answers[command] for command in commands]


def evaluate_batches(
    batches: list[list[str]],
    *,
    executable: str = "oracle",
) -> list[list[tuple[int, ...]]]:
    """Share stateless requests and retain each independent case's responses.

    Args:
        batches: Ordered request groups with independently assigned input tokens.
        executable: The Lake executable owning those checked definitions.

    Returns:
        One response group per case, preserving empty groups and request order.
    """
    commands = [command for batch in batches for command in batch]
    responses = iter(evaluate_distinct(commands, executable=executable))
    return [[next(responses) for _ in batch] for batch in batches]
