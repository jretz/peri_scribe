"""Prevent phase vocabulary drift and keep the domain independent of widgets."""

import ast
import graphlib
import pathlib

import peri_scribe.phases
import peri_scribe.pipeline_stages


def test_phase_catalogue_covers_every_identifier() -> None:
    identifiers = {*peri_scribe.phases.Phase, *peri_scribe.pipeline_stages.Stage}
    declared = {
        *peri_scribe.phases.CHILDREN,
        *(
            child
            for children in peri_scribe.phases.CHILDREN.values()
            for child in children
        ),
    }
    assert declared == identifiers
    graphlib.TopologicalSorter(peri_scribe.phases.CHILDREN).prepare()


def test_phase_logging_calls_use_typed_entry_point() -> None:
    directory = pathlib.Path(peri_scribe.phases.__file__).parent
    for path in directory.rglob("*.py"):
        if path.name == "logging.py":
            continue
        for node in ast.walk(ast.parse(path.read_text())):
            if isinstance(node, ast.Call) and isinstance(node.func, ast.Attribute):
                assert node.func.attr != "log_execution", (
                    f"Use log_phase: {path}:{node.lineno}"
                )
                if node.func.attr == "log_phase":
                    assert not isinstance(node.args[0], ast.Constant), (
                        f"Use a phase enum: {path}:{node.lineno}"
                    )


def test_monitor_domain_has_no_presentation_dependencies() -> None:
    directory = pathlib.Path(peri_scribe.phases.__file__).parent / "monitor"
    for name in ("events", "model", "storage"):
        tree = ast.parse((directory / f"{name}.py").read_text())
        for node in ast.walk(tree):
            if isinstance(node, ast.Import):
                assert all(
                    not alias.name.startswith((
                        "textual",
                        "rich",
                        "peri_scribe.monitor.app",
                        "peri_scribe.monitor.presentation",
                        "peri_scribe.monitor.widgets",
                    ))
                    for alias in node.names
                )
