"""Keep the package's explicit import dependencies acyclic."""

import ast
import graphlib
import pathlib

import pytest


def test_no_circular_imports() -> None:
    source_root = pathlib.Path(__file__).resolve().parents[3] / "src"
    modules = {
        ".".join(path.relative_to(source_root).with_suffix("").parts).removesuffix(
            ".__init__",
        ): path
        for path in sorted((source_root / "peri_scribe").rglob("*.py"))
    }
    assert modules, f"No source modules found under {source_root}"
    dependencies: dict[str, set[str]] = {name: set() for name in modules}

    for module_name, path in modules.items():
        tree = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))

        for node in ast.walk(tree):
            imported_names: set[str] = set()

            if isinstance(node, ast.Import):
                imported_names.update(alias.name for alias in node.names)
            elif isinstance(node, ast.ImportFrom):
                assert node.level == 0, (
                    f"Relative imports need resolver support: {path}:{node.lineno}"
                )
                if node.module:
                    imported_names.add(node.module)
                    imported_names.update(
                        f"{node.module}.{alias.name}" for alias in node.names
                    )

            dependencies[module_name].update(imported_names & modules.keys())

    try:
        graphlib.TopologicalSorter(dependencies).prepare()
    except graphlib.CycleError as error:
        cycle = " -> ".join(reversed(error.args[1]))
        pytest.fail(f"Circular import: {cycle}", pytrace=False)
