"""Keep package dependencies acyclic and rendering independent of the application."""

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
        for path in sorted(source_root.rglob("*.py"))
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


@pytest.mark.parametrize(
    ("package", "forbidden"),
    [
        ("arcgis_access", ("peri_scribe",)),
        ("aircraft_registration", ("peri_scribe",)),
        ("kml_io", ("peri_scribe",)),
        ("measurement_units", ("peri_scribe",)),
        ("spatial_data", ("peri_scribe", "arcgis_access")),
        ("svg_charts", ("peri_scribe",)),
        ("peri_scribe/presentation", ("peri_scribe.kml", "svg_charts", "kml_io")),
        ("peri_scribe/report", ("peri_scribe.kml",)),
    ],
)
def test_package_dependencies_respect_boundaries(
    package: str,
    forbidden: tuple[str, ...],
) -> None:
    directory = pathlib.Path(__file__).resolve().parents[3] / "src" / package
    paths = list(directory.rglob("*.py"))
    assert paths, f"Missing package: {directory}"
    for path in paths:
        for node in ast.walk(ast.parse(path.read_text(encoding="utf-8"))):
            if isinstance(node, ast.Import):
                names = [alias.name for alias in node.names]
            elif isinstance(node, ast.ImportFrom) and node.module:
                names = [node.module]
            else:
                continue
            assert all(
                name != dependency and not name.startswith(f"{dependency}.")
                for name in names
                for dependency in forbidden
            ), f"Package imports a forbidden dependency: {path}:{node.lineno}"
