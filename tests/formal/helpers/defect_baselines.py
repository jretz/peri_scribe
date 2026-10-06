"""Share successful pristine checks while keeping each changed source tree private."""

import dataclasses
import hashlib
import json
import pathlib
import shutil
import sys

import defusedxml.ElementTree

import tests.formal.helpers.oracle
import tests.formal.helpers.process


BOOTSTRAP = """
import importlib
import json
import pathlib
import sys
import pytest

source = pathlib.Path(sys.argv[1]).resolve()
sys.path.insert(0, str(source))
for name in json.loads(sys.argv[2]):
    module = importlib.import_module(name)
    assert pathlib.Path(module.__file__).resolve().is_relative_to(source)
raise SystemExit(pytest.main(sys.argv[3:]))
"""


@dataclasses.dataclass(frozen=True, kw_only=True)
class Target:
    """A pristine check identifies both its test and isolated production module."""

    module: str
    test: str


@dataclasses.dataclass(frozen=True, kw_only=True)
class Baseline:
    """Only the exact source snapshot and successfully executed checks may be reused."""

    files: dict[str, str]
    tests: tuple[str, ...]


def source_copy(directory: pathlib.Path) -> pathlib.Path:
    """Each interpreter receives ordinary private files, including package resources.

    Args:
        directory: This execution's private parent directory.

    Returns:
        The isolated source tree used for pristine or mutated execution.
    """
    root = tests.formal.helpers.oracle.DIRECTORY.parents[1]
    source = directory / "src"
    shutil.copytree(root / "src", source, ignore=shutil.ignore_patterns("__pycache__"))
    return source


def fingerprints(source: pathlib.Path) -> dict[str, str]:
    """A baseline must not authorize a different source snapshot or package resource.

    Args:
        source: The complete private source tree supplied to an interpreter.

    Returns:
        Content digests keyed by relative path, including non-Python resources.
    """
    return {
        str(path.relative_to(source)): hashlib.sha256(path.read_bytes()).hexdigest()
        for path in sorted(source.rglob("*"))
        if path.is_file() and "__pycache__" not in path.parts
    }


def command(
    source: pathlib.Path,
    directory: pathlib.Path,
    defects: tuple[Target, ...],
) -> list[str]:
    """Serial nested pytest retains the bootstrap's isolated production imports.

    Args:
        source: The pristine or mutated private package tree.
        directory: Private pytest storage and diagnostics.
        defects: Checks and owning production modules required in this interpreter.

    Returns:
        One subprocess command containing each requested check exactly once.
    """
    root = tests.formal.helpers.oracle.DIRECTORY.parents[1]
    return [
        sys.executable,
        "-B",
        "-c",
        BOOTSTRAP,
        str(source),
        json.dumps(tuple(dict.fromkeys(defect.module for defect in defects))),
        "-c",
        str(tests.formal.helpers.oracle.DIRECTORY / "pytest.ini"),
        "--numprocesses=0",
        "-o",
        f"pythonpath={source} {root}",
        "-p",
        "no:cacheprovider",
        "--basetemp",
        str(directory / "pytest"),
        "--tb=short",
        *(
            str(tests.formal.helpers.oracle.DIRECTORY / "conformance" / node)
            for node in dict.fromkeys(defect.test for defect in defects)
        ),
    ]


def checked_report(report: pathlib.Path, nodes: tuple[str, ...]) -> None:
    """A zero exit code alone cannot certify missing, skipped, or substituted checks.

    Args:
        report: JUnit diagnostics produced by the pristine pytest interpreter.
        nodes: Every unique target that was required to execute successfully.
    """
    cases = tuple(defusedxml.ElementTree.parse(report).iter("testcase"))
    assert len(cases) == len(nodes)
    assert all(not list(case) for case in cases)
    assert {
        f"{case.attrib['classname'].rsplit('.', 1)[-1]}.py::{case.attrib['name']}"
        for case in cases
    } == set(nodes)


def check(
    defects: tuple[Target, ...],
    directory: pathlib.Path,
) -> Baseline:
    """Publish evidence only after every unique pristine target passes unchanged.

    Args:
        defects: The selected mutations whose unchanged checks must pass first.
        directory: Temporary source, result, and pytest storage owned by the producer.

    Returns:
        Exact source identity and the complete inventory of passing baseline checks.
    """
    assert defects
    source = source_copy(directory)
    files = fingerprints(source)
    nodes = tuple(dict.fromkeys(defect.test for defect in defects))
    report = directory / "results.xml"
    result = tests.formal.helpers.process.run(
        [*command(source, directory, defects), f"--junitxml={report}"],
        cwd=tests.formal.helpers.oracle.DIRECTORY.parents[1],
        timeout=180,
    )
    assert result.returncode == 0, result.stdout + result.stderr
    checked_report(report, nodes)
    assert fingerprints(source) == files, "pristine checks changed their source tree"
    return Baseline(files=files, tests=nodes)
