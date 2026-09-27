import pathlib
import typing

import tests.formal.helpers.tlc


if typing.TYPE_CHECKING:
    import pytest


def test_explore_isolates_bundled_modules_and_cleans_temporary_storage(
    tmp_path: pathlib.Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    inherited = tmp_path / "shared"
    inherited.mkdir()
    monkeypatch.setenv("JAVA_TOOL_OPTIONS", f'-Djava.io.tmpdir="{inherited}"')
    directory = tmp_path / "exploration"
    dump, output = tests.formal.helpers.tlc.explore("RunState", "RunState", directory)
    modules = [
        pathlib.Path(line.removeprefix("Parsing file "))
        for line in output.splitlines()
        if line.startswith("Parsing file ") and line.endswith("/Naturals.tla")
    ]
    assert dump
    assert len(modules) == 1
    assert modules[0].is_relative_to(directory.resolve())
    assert not modules[0].parent.exists()
    assert not list(inherited.iterdir())
