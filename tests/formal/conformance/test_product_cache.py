import pathlib

import structlog.testing

import spatial_data.product_cache
import tests.formal.helpers.corpus
import tests.formal.helpers.product_cache


def test_read_matches_all_checked_cache_selections(tmp_path: pathlib.Path) -> None:
    states = tests.formal.helpers.corpus.states(
        "CacheRead",
        "CacheRead",
        tmp_path / "tlc",
    )
    assert len(states) == tests.formal.helpers.product_cache.READ_CASE_COUNT
    path = tmp_path / "products.sqlite"
    with (
        structlog.testing.capture_logs(),
        spatial_data.product_cache.scope(path, "policy"),
    ):
        previous = None
        for state in sorted(
            states,
            key=tests.formal.helpers.product_cache.read_configuration,
        ):
            configuration = tests.formal.helpers.product_cache.read_configuration(state)
            if configuration != previous:
                tests.formal.helpers.product_cache.prepare_read(state)
                previous = configuration
            tests.formal.helpers.product_cache.replay_read(state, path)


def test_scope_matches_every_checked_transaction_prefix(tmp_path: pathlib.Path) -> None:
    states = tests.formal.helpers.corpus.states(
        "ProductCache",
        "ProductCache",
        tmp_path / "tlc",
    )
    assert {int(state["phase"]) for state in states} == set(range(7))
    assert {state["interrupted"] for state in states} == {"TRUE", "FALSE"}
    assert {state["disabled"] for state in states} == {"TRUE", "FALSE"}
    for index, state in enumerate(states):
        tests.formal.helpers.product_cache.replay_transaction(
            state,
            tmp_path / f"prefix-{index}.sqlite",
        )
