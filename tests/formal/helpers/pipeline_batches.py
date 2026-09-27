"""Share actual execution prefixes while isolating independently checked branches."""

from __future__ import annotations

import collections.abc
import dataclasses
import pathlib
import shutil
import tempfile

import tests.formal.helpers.paths
import tests.formal.helpers.pipeline_composition


type History = tuple[tests.formal.helpers.pipeline_composition.Invocation, ...]
type Path = tests.formal.helpers.paths.Path[
    tests.formal.helpers.pipeline_composition.Durable
]


@dataclasses.dataclass(frozen=True, kw_only=True)
class Branch:
    """Only identical complete prefixes share execution and hidden TLC choices."""

    invocation: tests.formal.helpers.pipeline_composition.Invocation
    children: tuple[Branch, ...]
    terminal: bool


def trees(histories: collections.abc.Sequence[History]) -> tuple[Branch, ...]:
    """Keep a common invocation attached to its exact preceding history.

    Args:
        histories: Complete nonempty execution histories selected from TLC.

    Returns:
        Ordered prefix trees retaining every requested terminal history.
    """
    grouped: dict[
        tests.formal.helpers.pipeline_composition.Invocation,
        list[History],
    ] = {}
    for history in histories:
        assert history
        grouped.setdefault(history[0], []).append(history[1:])
    return tuple(
        Branch(
            invocation=invocation,
            children=trees(tuple(tail for tail in tails if tail)),
            terminal=any(not tail for tail in tails),
        )
        for invocation, tails in grouped.items()
    )


def histories(
    roots: tuple[Branch, ...],
    prefix: History = (),
) -> collections.abc.Iterator[History]:
    """Expose the complete case inventory independently of concrete execution.

    Args:
        roots: Complete prefix subtrees owned by this batch.
        prefix: Already traversed invocation choices.

    Yields:
        Every retained complete history exactly once.
    """
    for branch in roots:
        current = (*prefix, branch.invocation)
        if branch.terminal:
            yield current
        yield from histories(branch.children, current)


def weight(branch: Branch) -> int:
    """Estimate work without splitting a shared prefix across competing workers.

    Args:
        branch: One independently runnable subtree.

    Returns:
        The number of actual invocations needed to cover its continuations.
    """
    return 1 + sum(map(weight, branch.children))


def partition(roots: tuple[Branch, ...], count: int) -> tuple[tuple[Branch, ...], ...]:
    """Balance complete prefix trees while preserving their exact once-only ownership.

    Args:
        roots: The full checked inventory grouped by actual common prefixes.
        count: Positive number of collected pytest batches.

    Returns:
        Balanced batches that collectively retain every input history.
    """
    assert count > 0
    batches: list[list[Branch]] = [[] for _ in range(count)]
    weights = [0] * count
    for branch in sorted(roots, key=weight, reverse=True):
        index = min(range(count), key=weights.__getitem__)
        batches[index].append(branch)
        weights[index] += weight(branch)
    return tuple(tuple(batch) for batch in batches)


def replay(
    roots: tuple[Branch, ...],
    directory: pathlib.Path,
    checked: tests.formal.helpers.paths.Contract[
        tests.formal.helpers.pipeline_composition.Durable
    ],
) -> dict[History, Path]:
    """Continue real successful prefixes with independent, timestamp-preserving files.

    Args:
        roots: Complete prefix subtrees assigned to this worker's current test.
        directory: Private parent for all concrete branch directories.
        checked: The full checked graph and durable projection for these histories.

    Returns:
        Every requested history's actual surviving TLC execution and observed state.
    """
    directory.mkdir(parents=True, exist_ok=True)
    completed: dict[History, Path] = {}

    def visit(
        branch: Branch,
        prefix: History,
        parent: pathlib.Path | None,
        execution: Path | None,
    ) -> None:
        """A continuation inherits the actual full matcher and a faithful private copy.

        Args:
            branch: The next real invocation and its independently checked children.
            prefix: All preceding invocation choices, including their crash boundaries.
            parent: Real durable files after that exact successfully checked prefix.
            execution: Its full compatible TLC path, including hidden state choices.
        """
        with tempfile.TemporaryDirectory(dir=directory) as temporary:
            year = pathlib.Path(temporary) / "2026"
            if parent is not None:
                shutil.copytree(parent, year)
            path = tests.formal.helpers.pipeline_composition.replay(
                branch.invocation,
                year,
                checked,
                execution,
            )
            current = (*prefix, branch.invocation)
            if branch.terminal:
                assert current not in completed
                completed[current] = path
            for child in branch.children:
                visit(child, current, year, path)

    for branch in roots:
        visit(branch, (), None, None)
    return completed
