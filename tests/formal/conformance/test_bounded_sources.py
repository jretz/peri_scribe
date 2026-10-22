"""Real bounded source lifetimes follow continuously matched checked paths."""

import pathlib

import pytest

import tests.formal.helpers.bounded_sources
import tests.formal.helpers.corpus


@pytest.mark.parametrize("first_finished", [0, 1])
@pytest.mark.parametrize(
    "edit_at",
    [
        None,
        "before_pin",
        "pin",
        "metadata",
        "ownership",
        "work",
        "validated",
        "released",
        "published",
    ],
)
def test_bounded_sources_preserve_checked_source_edit_paths(
    tmp_path: pathlib.Path,
    edit_at: str | None,
    first_finished: int,
) -> None:
    graph = tests.formal.helpers.corpus.graph(
        "BoundedSourceRead",
        "BoundedSourceRead",
        tmp_path / "model",
    )
    tests.formal.helpers.bounded_sources.Observer(
        year=tmp_path / "year",
        checked_contract=tests.formal.helpers.bounded_sources.contract(graph),
        edit_at=edit_at,
        first_finished=first_finished,
    ).run()


@pytest.mark.parametrize("first_finished", [0, 1])
@pytest.mark.parametrize("poison", ["metadata", "ownership", "geometry"])
@pytest.mark.parametrize("bad_blocks", [("first",), ("second",), ("first", "second")])
def test_bounded_sources_preserve_checked_refusal_paths(
    tmp_path: pathlib.Path,
    poison: str,
    bad_blocks: tuple[str, ...],
    first_finished: int,
) -> None:
    graph = tests.formal.helpers.corpus.graph(
        "BoundedSourceRead",
        "BoundedSourceRead",
        tmp_path / "model",
    )
    tests.formal.helpers.bounded_sources.Observer(
        year=tmp_path / "year",
        checked_contract=tests.formal.helpers.bounded_sources.contract(graph),
        poison=poison,
        bad_blocks=bad_blocks,
        first_finished=first_finished,
    ).run()
