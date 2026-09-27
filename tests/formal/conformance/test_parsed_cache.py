import collections
import pathlib
import typing


if typing.TYPE_CHECKING:
    import pytest

import tests.formal.helpers.parsed_cache
import tests.formal.helpers.tlc


def test_fetch_snapshot_rows_matches_checked_transaction_schedules(
    tmp_path: pathlib.Path,
) -> None:
    states = tests.formal.helpers.tlc.states(
        "ParsedCacheRead",
        "ParsedCacheRead",
        tmp_path / "tlc",
    )
    terminals = [state for state in states if state["phase"] == "3"]
    assert len(terminals) == tests.formal.helpers.parsed_cache.READ_SCHEDULE_COUNT
    for index, state in enumerate(terminals):
        tests.formal.helpers.parsed_cache.replay_read(
            state,
            tmp_path / f"read-{index}.sqlite",
        )


def test_sync_database_matches_checked_commits_and_interruptions(
    tmp_path: pathlib.Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    graph = tests.formal.helpers.tlc.graph(
        "ParsedCache",
        "ParsedCache",
        tmp_path / "tlc",
    )
    configurations: dict[tuple[str, str], list[dict[str, str]]] = (
        collections.defaultdict(
            list,
        )
    )
    for state in graph.states.values():
        configurations[state["initial"], state["target"]].append(state)
    assert (
        len(configurations)
        == tests.formal.helpers.parsed_cache.SYNC_CONFIGURATION_COUNT
    )
    schedules = sum(
        tests.formal.helpers.parsed_cache.replay_sync(
            records,
            tmp_path / f"sync-{index}",
            monkeypatch,
            graph,
        )
        for index, records in enumerate(configurations.values())
    )
    assert schedules == tests.formal.helpers.parsed_cache.SYNC_INTERRUPTION_COUNT


def test_reset_database_matches_checked_schema_interruptions(
    tmp_path: pathlib.Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    graph = tests.formal.helpers.tlc.graph(
        "ParsedCacheRebuild",
        "ParsedCacheRebuild",
        tmp_path / "tlc",
    )
    prefixes = [
        state
        for state in graph.states.values()
        if state["restarted"] == "FALSE"
        and int(state["phase"]) < tests.formal.helpers.parsed_cache.SCHEMA_PREFIX_COUNT
    ]
    assert len(prefixes) == 2 * tests.formal.helpers.parsed_cache.SCHEMA_PREFIX_COUNT
    for index, state in enumerate(prefixes):
        tests.formal.helpers.parsed_cache.replay_rebuild(
            state,
            tmp_path / f"schema-{index}",
            monkeypatch,
            graph,
        )
