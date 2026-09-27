"""Replay checked staging boundaries through the production publication context."""

import pathlib

import pytest

import peri_scribe.sources.downloading


class Interrupted(BaseException):
    """Represent cancellation that bypasses ordinary conversion exception handlers."""


def write_chunks(
    output: pathlib.Path,
    *,
    fail_after: int | None,
    states: list[dict[str, str]],
) -> None:
    """Observe the published path at every modeled prefix, including interrupted ones.

    Args:
        output: An isolated final destination.
        fail_after: Number of staged chunks before cancellation, or None for success.
        states: States exported from the checked three-chunk download model.

    Raises:
        Interrupted: At the requested incomplete or complete-but-unpublished prefix.
    """
    with peri_scribe.sources.downloading.completed_download(output) as temporary:
        for count in range(4):
            checked = next(
                state
                for state in states
                if state["staged"] == str(count)
                and state["phase"] == '"build"'
                and state["final"] == "0"
            )
            assert output.exists() == (checked["final"] != "0")
            temporary.write_text("x" * count)
            if count == fail_after:
                raise Interrupted
    completed = next(
        state
        for state in states
        if state["phase"] == '"done"' and state["staged"] == "3"
    )
    assert len(output.read_text(encoding="utf-8")) == int(completed["final"])


def replay(states: list[dict[str, str]], directory: pathlib.Path) -> None:
    """Check cancellation at every prefix and then complete a fresh retry.

    Args:
        states: The checked download graph.
        directory: Isolated output root.
    """
    for fail_after in range(4):
        output = directory / str(fail_after) / "source.gpkg"
        with pytest.raises(Interrupted):
            write_chunks(output, fail_after=fail_after, states=states)
        assert list(output.parent.iterdir()) == []
        write_chunks(output, fail_after=None, states=states)
