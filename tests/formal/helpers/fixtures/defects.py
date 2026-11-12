"""Require complete current native evidence before accepting selected source mutations.

Design notes:
[Verification evidence and execution](
    ../../../../docs/algorithms/verification-tooling.md).
"""

import collections.abc
import functools
import hashlib
import pathlib

import pydantic
import pytest

import tests.formal.helpers.corpus
import tests.formal.helpers.defect_baselines
import tests.formal.helpers.defect_checks
import tests.formal.helpers.oracle
import tests.formal.helpers.session


def baseline_name(
    defects: tuple[tests.formal.helpers.defect_checks.Defect, ...],
) -> str:
    """Identify one exact inventory of selected deliberate defects.

    Args:
        defects: The selected mutations whose pristine tests must pass.

    Returns:
        The shared artifact name independent of worker collection order.
    """
    identity = hashlib.sha256(
        "\n".join(sorted(defect.name for defect in defects)).encode(),
    ).hexdigest()
    return f"defect-baseline-{identity}"


def selected_defects(
    items: collections.abc.Iterable[pytest.Item],
) -> tuple[tests.formal.helpers.defect_checks.Defect, ...]:
    """Identify only the concrete mutant cases selected for execution.

    Args:
        items: This worker's current collection.

    Returns:
        The selected defects in collection order.
    """
    return tuple(
        defect
        for item in items
        if isinstance(item, pytest.Function) and hasattr(item, "callspec")
        for defect in (item.callspec.params.get("defect"),)
        if isinstance(defect, tests.formal.helpers.defect_checks.Defect)
    )


def pytest_addoption(parser: pytest.Parser) -> None:
    """Register the integrated suite's coverage partition.

    Args:
        parser: The controller or worker pytest parser.
    """
    parser.addoption(
        tests.formal.helpers.defect_baselines.USE_PRISTINE_TARGETS,
        action="store_true",
        help="Run exact mutation targets through the verified pristine baseline",
    )


def remove_targets(
    items: list[pytest.Item],
    targets: set[str],
) -> list[pytest.Item]:
    """Move only exact node IDs into the independently checked pristine session.

    Args:
        items: Collection retained after pytest's ordinary selection.
        targets: Full node IDs assigned to the pristine session.

    Returns:
        The removed items for pytest's deselection notification.

    Raises:
        pytest.UsageError: If any exact target is missing or collected more than once.
    """
    removed = [item for item in items if item.nodeid in targets]
    if len(removed) != len(targets) or {item.nodeid for item in removed} != targets:
        message = "Integrated conformance requires each exact pristine target once"
        raise pytest.UsageError(message)
    items[:] = [item for item in items if item.nodeid not in targets]
    return removed


@pytest.hookimpl(trylast=True)
def pytest_collection_modifyitems(
    config: pytest.Config,
    items: list[pytest.Item],
) -> None:
    """Keep the complete mutation inventory when moving pristine targets.

    Args:
        config: The pytest configuration for this collection.
        items: Collected test cases after ordinary selection.

    Raises:
        pytest.UsageError: If filtering removed any registered mutation case.
    """
    if not config.getoption(tests.formal.helpers.defect_baselines.USE_PRISTINE_TARGETS):
        return
    registered = tests.formal.helpers.defect_checks.DEFECTS
    selected = selected_defects(items)
    if len(selected) != len(registered) or set(selected) != set(registered):
        message = "Integrated conformance requires every registered mutation case"
        raise pytest.UsageError(message)
    removed = remove_targets(
        items,
        {f"conformance/{defect.test}" for defect in selected},
    )
    config.hook.pytest_deselected(items=removed)


def require_pristine_targets(directory: pathlib.Path) -> int:
    """Require exact successful target receipts for this run's unchanged source tree.

    Args:
        directory: The live, fresh checked evidence directory of this invocation.

    Returns:
        The number of exact target cases verified by the pristine run.

    Raises:
        ValueError: If source digests or passed target identities do not match.
    """
    registered = tests.formal.helpers.defect_checks.DEFECTS
    receipt = directory / f"{baseline_name(registered)}.json"
    baseline = pydantic.TypeAdapter(
        tests.formal.helpers.defect_baselines.Baseline,
    ).validate_json(receipt.read_bytes())
    targets = {defect.test for defect in registered}
    if len(baseline.tests) != len(targets) or set(baseline.tests) != targets:
        message = "Pristine receipt does not match the removed conformance targets"
        raise ValueError(message)
    source = tests.formal.helpers.oracle.DIRECTORY.parents[1] / "src"
    if baseline.files != tests.formal.helpers.defect_baselines.fingerprints(source):
        message = "Pristine receipt does not match the current production source"
        raise ValueError(message)
    return len(targets)


def pytest_sessionfinish(session: pytest.Session, exitstatus: int) -> None:
    """Fail the controller if any moved target lacks a fresh passing receipt.

    Args:
        session: The completed pytest session.
        exitstatus: The exit status before checking the pristine receipt.
    """
    if (
        exitstatus != pytest.ExitCode.OK
        or not session.config.getoption(
            tests.formal.helpers.defect_baselines.USE_PRISTINE_TARGETS,
        )
        or hasattr(session.config, "workerinput")
    ):
        return
    directory = tests.formal.helpers.session.directory()
    assert directory is not None
    try:
        count = require_pristine_targets(directory)
    except (OSError, ValueError) as error:
        pytest.exit(f"Pristine conformance evidence failed: {error}", returncode=1)
    print(f"\n{count} pristine conformance targets passed in the isolated baseline.")


def load_baseline(
    directory: pathlib.Path,
    selected: tuple[tests.formal.helpers.defect_checks.Defect, ...],
) -> tests.formal.helpers.defect_baselines.Baseline:
    """Publish one pristine receipt for an exact inventory of mutation targets.

    Args:
        directory: Shared temporary storage for this formal invocation.
        selected: Mutations whose targets must pass on unchanged source.

    Returns:
        Passing baseline targets tied to the exact source and resource contents.
    """
    assert selected
    return tests.formal.helpers.corpus.load(
        directory,
        baseline_name(selected),
        pydantic.TypeAdapter(tests.formal.helpers.defect_baselines.Baseline),
        functools.partial(
            tests.formal.helpers.defect_baselines.check,
            tuple(
                tests.formal.helpers.defect_baselines.Target(
                    module=defect.module,
                    test=defect.test,
                )
                for defect in selected
            ),
        ),
    )


@pytest.fixture(scope="session")
def formal_defect_baseline(
    request: pytest.FixtureRequest,
    formal_corpus_directory: pathlib.Path,
) -> tests.formal.helpers.defect_baselines.Baseline:
    """Selected workers share complete immutable evidence from the current native owner.

    Args:
        request: The complete collection retained by this worker.
        formal_corpus_directory: Shared temporary storage for this formal invocation.

    Returns:
        Passing baseline targets tied to the exact source and resource contents.
    """
    selected = selected_defects(request.session.items)
    return load_baseline(formal_corpus_directory, selected)


def main() -> None:
    """Prepare native target evidence in a subprocess owned by the combined gate.

    Raises:
        RuntimeError: If the parent has no live formal evidence session.
    """
    directory = tests.formal.helpers.session.directory()
    if directory is None:
        message = "Pristine preparation requires a live formal evidence session"
        raise RuntimeError(message)
    load_baseline(directory, tests.formal.helpers.defect_checks.DEFECTS)


if __name__ == "__main__":
    main()
