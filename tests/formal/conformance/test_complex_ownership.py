"""Actual Lean outcomes constrain source-derived temporal complex ownership."""

import pathlib
import unittest.mock

import pytest

import peri_scribe.fires.sources
import tests.formal.helpers.complex_aliases
import tests.formal.helpers.complex_ownership
import tests.formal.helpers.oracle


def test_group_fire_sources_matches_lean_temporal_complex_ownership() -> None:
    cases = tests.formal.helpers.complex_ownership.cases()
    expected = tests.formal.helpers.oracle.evaluate(
        [tests.formal.helpers.complex_ownership.command(case) for case in cases],
        executable="oracleComplex",
    )
    expected_count = 2197
    assert len(cases) == expected_count
    for case, outcome in zip(cases, expected, strict=True):
        for equivalent in (case, tuple(reversed(case)), (*case, *case)):
            read = tests.formal.helpers.complex_ownership.source_history(equivalent)
            groups = peri_scribe.fires.sources.group_fire_sources(read)
            assert (
                tests.formal.helpers.complex_ownership.projection(groups) == outcome
            ), case


def test_group_fire_sources_matches_lean_after_parsed_cache_roundtrip(
    tmp_path: pathlib.Path,
) -> None:
    cases = tests.formal.helpers.complex_ownership.cases()[1729::10]
    expected = tests.formal.helpers.oracle.evaluate(
        [tests.formal.helpers.complex_ownership.command(case) for case in cases],
        executable="oracleComplex",
    )
    for index, (case, outcome) in enumerate(zip(cases, expected, strict=True)):
        read = tests.formal.helpers.complex_ownership.cached_history(
            case,
            tmp_path / f"history-{index}.db",
        )
        groups = peri_scribe.fires.sources.group_fire_sources(read)
        assert tests.formal.helpers.complex_ownership.projection(groups) == outcome, (
            case
        )


def test_group_fire_sources_matches_lean_with_standalone_cached_declarations(
    tmp_path: pathlib.Path,
) -> None:
    cases = tests.formal.helpers.complex_ownership.cases()[1729::10]
    expected = tests.formal.helpers.oracle.evaluate(
        [tests.formal.helpers.complex_ownership.command(case) for case in cases],
        executable="oracleComplex",
    )
    for index, (case, outcome) in enumerate(zip(cases, expected, strict=True)):
        read = tests.formal.helpers.complex_ownership.cached_history(
            case,
            tmp_path / f"standalone-{index}.db",
            standalone=True,
        )
        groups = peri_scribe.fires.sources.group_fire_sources(read)
        assert tests.formal.helpers.complex_ownership.projection(groups) == outcome, (
            case
        )


@pytest.mark.parametrize("cached", [False, True], ids=["source", "cache"])
def test_group_fire_sources_matches_lean_with_mixed_dated_declarations(
    tmp_path: pathlib.Path,
    *,
    cached: bool,
) -> None:
    cases = tests.formal.helpers.complex_ownership.mixed_histories()
    expected = tests.formal.helpers.oracle.evaluate(
        [tests.formal.helpers.complex_ownership.command(case) for case in cases],
        executable="oracleComplex",
    )
    expected_count = 8
    assert len(cases) == expected_count
    for index, (case, outcome) in enumerate(zip(cases, expected, strict=True)):
        for order, equivalent in enumerate((
            case,
            tuple(reversed(case)),
            (*case, *case),
        )):
            if cached:
                read = tests.formal.helpers.complex_ownership.cached_history(
                    equivalent,
                    tmp_path / f"mixed-{index}-{order}.db",
                )
            else:
                read = tests.formal.helpers.complex_ownership.source_history(equivalent)
            groups = peri_scribe.fires.sources.group_fire_sources(read)
            assert (
                tests.formal.helpers.complex_ownership.projection(groups) == outcome
            ), case


@pytest.mark.parametrize("location", [False, True], ids=["perimeters", "locations"])
def test_group_fire_sources_matches_lean_with_incomplete_aliased_source_rows(
    tmp_path: pathlib.Path,
    *,
    location: bool,
) -> None:
    cases = tests.formal.helpers.complex_aliases.cases(location=location)
    expected = tests.formal.helpers.oracle.evaluate(
        [
            tests.formal.helpers.complex_ownership.command(case.history)
            for case in cases
        ],
        executable="oracleComplex",
    )
    expected_count = 6
    assert len(cases) == expected_count
    for index, (case, outcome) in enumerate(zip(cases, expected, strict=True)):
        for order in ("original", "reversed", "duplicated"):
            directory = tests.formal.helpers.complex_aliases.write_history(
                case,
                tmp_path / f"aliases-{index}-{order}",
                order,
            )
            read = peri_scribe.fires.sources.read_fire_sources(directory)
            groups = peri_scribe.fires.sources.group_fire_sources(read)
            assert tests.formal.helpers.complex_ownership.projection(groups) == outcome
            with unittest.mock.patch(
                "peri_scribe.geo.package.read_geopackage",
                side_effect=AssertionError(
                    "A warm cache must retain every declaration",
                ),
            ):
                cached = peri_scribe.fires.sources.read_fire_sources(directory)
            groups = peri_scribe.fires.sources.group_fire_sources(cached)
            assert tests.formal.helpers.complex_ownership.projection(groups) == outcome
