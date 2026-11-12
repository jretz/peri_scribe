import pathlib

import pytest

import tests.formal.helpers.tlc


TEMPORAL = "Checking temporal properties for the complete state space\n"
COUNT = "4 states generated, 2 distinct states found, 0 states left on queue.\n"


def test_decode_states_retains_raw_field_order_after_temporal_stutters() -> None:
    first = '/\\ phase = "read"\n/\\ value = <<0,\n  1>>\n\n'
    second = '/\\ phase = "done"\n/\\ value = <<2>>\n\n'
    dump = "".join(
        f"State {index}:\n{label}"
        for index, label in enumerate((first, second, first, second), 1)
    )
    states = tests.formal.helpers.tlc.decode_states(dump, TEMPORAL + COUNT)
    assert [tuple(state.items()) for state in states] == [
        (("phase", '"read"'), ("value", "<<0,\n  1>>")),
        (("phase", '"done"'), ("value", "<<2>>")),
    ]


@pytest.mark.parametrize(
    ("values", "numbers", "temporal", "error"),
    [
        ("01", (1, 3), "", "nonconsecutive"),
        ("0", (1,), "", "state count differs"),
        ("001", (1, 2, 3), "", "multiplicity"),
        ("0001", (1, 2, 3, 4), TEMPORAL, "multiplicity"),
    ],
)
def test_decode_states_rejects_an_incomplete_inventory(
    values: str,
    numbers: tuple[int, ...],
    temporal: str,
    error: str,
) -> None:
    dump = "".join(
        f"State {number}:\n/\\ x = {value}\n\n"
        for number, value in zip(numbers, values, strict=True)
    )
    with pytest.raises(AssertionError, match=error):
        tests.formal.helpers.tlc.decode_states(dump, temporal + COUNT)


def test_decode_states_rejects_a_truncated_last_label() -> None:
    dump = "State 1:\n/\\ x = 0\n\nState 2:\n/\\ x = <<0, 1"
    with pytest.raises(AssertionError, match="incomplete TLC state export"):
        tests.formal.helpers.tlc.decode_states(dump, COUNT)


@pytest.mark.parametrize(
    ("label", "error"),
    [
        ("extra text\n/\\ x = 1", "unparsed TLC state label"),
        ("/\\ x = 1\n/\\ x = 2", "repeated TLC state field"),
        ("/\\ x  = 1", "unparsed TLC state field"),
    ],
)
def test_decode_states_requires_the_complete_label(label: str, error: str) -> None:
    dump = f"State 1:\n/\\ x = 0\n\nState 2:\n{label}\n\n"
    with pytest.raises(AssertionError, match=error):
        tests.formal.helpers.tlc.decode_states(dump, COUNT)


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
