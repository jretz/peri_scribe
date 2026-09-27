"""Execute the compiled definitions whose properties Lean checks."""

import pathlib

import tests.formal.helpers.process


DIRECTORY = pathlib.Path(__file__).resolve().parents[1]


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
    result = tests.formal.helpers.process.run(
        [str(path)],
        standard_input="\n".join(commands) + "\n",
    )
    assert result.returncode == 0, result.stdout + result.stderr
    responses = [tuple(map(int, line.split())) for line in result.stdout.splitlines()]
    assert len(responses) == len(commands), result.stderr
    return responses
