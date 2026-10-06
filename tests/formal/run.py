"""Run formal phases in order with fresh checked evidence shared across their tools."""

import pathlib
import shutil
import sys

import pytest

import tests.formal.check
import tests.formal.helpers.process
import tests.formal.helpers.session


DIRECTORY = pathlib.Path(__file__).resolve().parents[2]


def phases() -> int:
    """Each independent proof job retains its own cancellation and cleanup boundary.

    Returns:
        The first unsuccessful phase's exit status, or zero after all phases pass.

    Raises:
        RuntimeError: If the registered Lean toolchain is unavailable.
    """
    status = tests.formal.check.main(["tla"])
    if status:
        return status
    lake = shutil.which("lake")
    if lake is None:
        message = "Run through mise formal to provide the Lean toolchain"
        raise RuntimeError(message)
    result = tests.formal.helpers.process.run(
        [lake, "build"],
        cwd=DIRECTORY / "tests" / "formal" / "lean",
        timeout=3600,
    )
    print(result.stdout, end="", flush=True)
    print(result.stderr, end="", file=sys.stderr, flush=True)
    if result.returncode:
        return result.returncode
    status = pytest.main(
        [
            "-c",
            str(DIRECTORY / "tests" / "formal" / "pytest.ini"),
            str(DIRECTORY / "tests" / "formal" / "conformance"),
        ],
    )
    if status:
        return int(status)
    return tests.formal.check.main(["counterexamples"])


def main() -> int:
    """A temporary session prevents successful evidence from outliving this invocation.

    Returns:
        The complete suite's success or first failing phase's exit status.
    """
    with tests.formal.helpers.session.temporary():
        return phases()


if __name__ == "__main__":
    raise SystemExit(main())
