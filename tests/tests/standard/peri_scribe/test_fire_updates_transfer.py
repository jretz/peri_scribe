"""Corrections transfer saved history without overwriting its mapping evidence."""

import dataclasses
import datetime
import json
import pathlib

import pytest
import shapely

import peri_scribe.fire_updates
import peri_scribe.models
import tests.helpers.factories.peri_scribe.fire_updates_ownership
import tests.helpers.factories.peri_scribe.fire_updates_transfer


def test_prepare_updates_inherits_every_history_without_relogging_known_mapping(
    tmp_path: pathlib.Path,
) -> None:
    first = tests.helpers.factories.peri_scribe.fire_updates_transfer.fire(
        frozenset({"a"}),
        1,
    )
    second = tests.helpers.factories.peri_scribe.fire_updates_transfer.fire(
        frozenset({"b"}),
        2,
    )
    saved = tests.helpers.factories.peri_scribe.fire_updates_ownership.publish_updates(
        tmp_path,
        [first, second],
        tests.helpers.factories.peri_scribe.fire_updates_transfer.EPOCH,
    )
    merged = dataclasses.replace(
        second,
        identifiers=first.identifiers | second.identifiers,
        perimeters=first.perimeters + second.perimeters,
    )

    prepared = peri_scribe.fire_updates.prepare_updates(
        tmp_path,
        [merged],
        peri_scribe.models.FireScores(version="test", fires=[]),
    )

    assert prepared.records == ()
    for key, signatures in saved.state.perimeters.items():
        assert signatures <= prepared.state.perimeters[key]


@pytest.mark.parametrize("reverse_order", [False, True])
def test_prepare_updates_gives_shared_history_to_latest_mapped_claimant(
    tmp_path: pathlib.Path,
    *,
    reverse_order: bool,
) -> None:
    original = tests.helpers.factories.peri_scribe.fire_updates_transfer.fire(
        frozenset({"a", "b"}),
        1,
    )
    saved = tests.helpers.factories.peri_scribe.fire_updates_ownership.publish_updates(
        tmp_path,
        [original],
        tests.helpers.factories.peri_scribe.fire_updates_transfer.EPOCH,
    )
    latest = tests.helpers.factories.peri_scribe.fire_updates_transfer.fire(
        frozenset({"a"}),
        3,
        name="Latest",
    )
    older = tests.helpers.factories.peri_scribe.fire_updates_transfer.fire(
        frozenset({"b"}),
        2,
        name="Older",
    )
    fires = [older, latest] if reverse_order else [latest, older]

    prepared = peri_scribe.fire_updates.prepare_updates(
        tmp_path,
        fires,
        peri_scribe.models.FireScores(version="test", fires=[]),
    )

    original_key = saved.state.aliases[json.dumps(["id", "a"])]
    latest_key = prepared.state.aliases[json.dumps(["id", "a"])]
    older_key = prepared.state.aliases[json.dumps(["id", "b"])]
    assert latest_key == original_key
    assert older_key != original_key
    assert {json.dumps(record["log_identity"]) for record in prepared.records} == {
        latest_key,
        older_key,
    }


def test_prepare_updates_keeps_a_losing_claimants_route_to_reclaim_history(
    tmp_path: pathlib.Path,
) -> None:
    original = tests.helpers.factories.peri_scribe.fire_updates_transfer.fire(
        frozenset({"a", "b"}),
        1,
    )
    saved = tests.helpers.factories.peri_scribe.fire_updates_ownership.publish_updates(
        tmp_path,
        [original],
        tests.helpers.factories.peri_scribe.fire_updates_transfer.EPOCH,
    )
    original_key = saved.state.aliases[json.dumps(["id", "a"])]
    for step, (first_time, second_time) in enumerate(((2, 3), (4, 3), (4, 5)), 1):
        first = tests.helpers.factories.peri_scribe.fire_updates_transfer.fire(
            frozenset({"a"}),
            first_time,
            name="First",
        )
        second = tests.helpers.factories.peri_scribe.fire_updates_transfer.fire(
            frozenset({"b"}),
            second_time,
            name="Second",
        )
        prepared = (
            tests.helpers.factories.peri_scribe.fire_updates_ownership.publish_updates(
                tmp_path,
                [first, second],
                tests.helpers.factories.peri_scribe.fire_updates_transfer.EPOCH
                + datetime.timedelta(minutes=step),
            )
        )
        winner = "a" if first_time > second_time else "b"
        winner_key = prepared.state.aliases[json.dumps(["id", winner])]
        assert prepared.state.owners[original_key] == winner_key


@pytest.mark.parametrize(
    ("first_time", "second_time", "winner"),
    [(None, -600000, "b"), (-600000, None, "a"), (None, None, "b"), (2, 2, "b")],
)
def test_resolved_ownership_handles_missing_dates_and_ties_deterministically(
    first_time: int | None,
    second_time: int | None,
    winner: str,
) -> None:
    history = json.dumps(["id", "original"])
    fires = {
        ("id", identifier): (
            tests.helpers.factories.peri_scribe.fire_updates_transfer.fire(
                frozenset({identifier}),
                observed,
            )
        )
        for identifier, observed in (("a", first_time), ("b", second_time))
    }
    previous = peri_scribe.fire_updates.State(
        aliases=dict.fromkeys((json.dumps(identity) for identity in fires), history),
    )
    evidence = dict.fromkeys(fires, frozenset())

    resolved = peri_scribe.fire_updates.resolved_ownership(
        fires,
        previous,
        evidence,
        evidence,
    )

    assert resolved.keys["id", winner] == history
    assert resolved == peri_scribe.fire_updates.resolved_ownership(
        dict(reversed(tuple(fires.items()))),
        previous,
        evidence,
        evidence,
    )


def test_mapping_priority_uses_latest_nonempty_mapping_anywhere_in_history() -> None:
    latest = tests.helpers.factories.peri_scribe.fire_updates_transfer.fire(
        frozenset({"a"}),
        3,
    )
    older = tests.helpers.factories.peri_scribe.fire_updates_transfer.fire(
        frozenset({"a"}),
        1,
    )
    future_empty = dataclasses.replace(
        latest.perimeters[0],
        geometry=shapely.Polygon(),
        observation_time=(
            tests.helpers.factories.peri_scribe.fire_updates_transfer.EPOCH
            + datetime.timedelta(days=1)
        ),
    )
    reordered = dataclasses.replace(
        latest,
        perimeters=(*latest.perimeters, future_empty, *older.perimeters),
    )

    assert peri_scribe.fire_updates.mapping_priority(reordered) == (
        peri_scribe.fire_updates.mapping_priority(latest)
    )


def test_history_keys_reserves_buckets_mentioned_only_by_lineage_or_ownership() -> None:
    histories = {json.dumps(["local", str(index)]) for index in range(3)}
    first, second, third = sorted(histories)
    previous = peri_scribe.fire_updates.State(
        lineage={json.dumps(["id", "a"]): frozenset({first})},
        owners={second: third},
    )

    assert peri_scribe.fire_updates.history_keys(previous) == histories
