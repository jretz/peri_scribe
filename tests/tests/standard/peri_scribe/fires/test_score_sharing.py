"""Preserve scoring identity rules while sharing presentation histories."""

from __future__ import annotations

import pathlib
import typing

import pytest

import peri_scribe.areas
import peri_scribe.execution
import peri_scribe.fires.differential
import peri_scribe.fires.identity
import peri_scribe.fires.index
import peri_scribe.fires.score_files
import peri_scribe.fires.scores
import peri_scribe.fires.sources
import peri_scribe.output
import peri_scribe.sources.snapshots
import tests.helpers.doubles.errors
import tests.helpers.doubles.peri_scribe.fires.scores
import tests.helpers.factories.geography
import tests.helpers.factories.peri_scribe.fires.scores
import tests.helpers.factories.peri_scribe.kml.parsing
from measurement_units import units


@pytest.mark.parametrize(
    ("contents", "unreadable"),
    [
        pytest.param(b'{"version": "1", "fires": [', False, id="truncated-json"),
        pytest.param(b'{"version": "1", "fires": {}}', False, id="invalid-schema"),
        pytest.param(b"\xff", False, id="invalid-encoding"),
        pytest.param(b'{"version": "1", "fires": []}', True, id="unreadable"),
    ],
)
def test_score_fires_preserves_outputs_when_optional_source_index_is_unusable(
    tmp_path: pathlib.Path,
    monkeypatch: pytest.MonkeyPatch,
    classified_history_inputs: list[peri_scribe.fires.sources.ReadFireSources],
    contents: bytes,
    *,
    unreadable: bool,
) -> None:
    peri_scribe.fires.differential.write_history_of_differential_geography(tmp_path)
    score_path = peri_scribe.fires.scores.score_fires(tmp_path)
    chart_path = peri_scribe.fires.score_files.fire_scores_ccdf_path(tmp_path)
    expected = (score_path.read_bytes(), chart_path.read_bytes())
    index_path = peri_scribe.sources.snapshots.fire_index_path(tmp_path)
    index_path.parent.mkdir(parents=True, exist_ok=True)
    index_path.write_bytes(contents)
    monkeypatch.setattr(
        peri_scribe.fires.index,
        "index_fire_sources",
        tests.helpers.doubles.errors.raising_stub(
            AssertionError("Standalone scoring must not rebuild the source index"),
        ),
    )
    if unreadable:
        monkeypatch.setattr(
            peri_scribe.output,
            "read_document",
            tests.helpers.doubles.errors.raising_stub(
                PermissionError("Source index is unreadable"),
            ),
        )

    peri_scribe.fires.scores.score_fires(tmp_path)

    assert (score_path.read_bytes(), chart_path.read_bytes()) == expected
    assert index_path.read_bytes() == contents


def test_aligned_positions_preserves_alias_order_with_duplicate_index_labels() -> None:
    frame = tests.helpers.factories.peri_scribe.fires.scores.reported_frame([
        ("alias", "Example", 100),
        ("other", "Other", 200),
        ("canonical", "Example", 300),
        ("alias", "Example", 400),
    ])
    frame.index = [4, 4, 4, 4]

    scoring, presentation = peri_scribe.fires.scores.aligned_positions(
        frame,
        {"alias": "canonical"},
    )

    assert scoring == {"alias": [0, 3], "other": [1], "canonical": [2]}
    assert presentation == {
        ("id", "canonical"): [0, 2, 3],
        ("id", "other"): [1],
    }


def test_aligned_positions_keeps_identifier_and_name_collisions_distinct() -> None:
    frame = tests.helpers.factories.peri_scribe.fires.scores.reported_frame([
        ("name:Smoke", "Different", 100),
        (None, "Smoke", 200),
    ])

    scoring, presentation = peri_scribe.fires.scores.aligned_positions(frame, {})

    assert scoring == {"name:Smoke": [0, 1]}
    assert presentation == {("id", "name:Smoke"): [0], ("name", "Smoke"): [1]}


def test_aligned_positions_accepts_empty_layers_without_identity_columns() -> None:
    assert peri_scribe.fires.scores.aligned_positions(
        tests.helpers.factories.geography.empty_frame(),
        {},
    ) == ({}, {})


@pytest.mark.parametrize(
    ("canonical_identifier", "identifiers", "expected_keys"),
    [
        ("canonical", ["canonical"], {"canonical"}),
        ("canonical", ["alias"], {"alias"}),
        ("canonical", ["canonical", "alias"], set()),
        ("canonical", [None], {"name:Example"}),
        (None, ["alias"], {"alias"}),
    ],
)
def test_matching_histories_reuses_only_identical_alias_groups(
    tmp_path: pathlib.Path,
    canonical_identifier: str | None,
    identifiers: list[str | None],
    expected_keys: set[str],
) -> None:
    index = tests.helpers.factories.peri_scribe.kml.parsing.fire_index([
        tests.helpers.factories.peri_scribe.kml.parsing.fire_index_entry(
            "Example",
            "active",
            identifier=canonical_identifier,
            aliases=["alias"],
        ),
    ])
    tests.helpers.factories.peri_scribe.fires.scores.write_fire_index(tmp_path, index)
    empty = tests.helpers.factories.geography.empty_frame()
    points = tests.helpers.factories.peri_scribe.fires.scores.reported_frame([
        (identifier, "Example", 100 + position)
        for position, identifier in enumerate(identifiers)
    ])
    points.index = [9] * len(points)

    with peri_scribe.execution.sharing():
        histories = peri_scribe.fires.scores.matching_histories(
            tmp_path,
            empty,
            points,
            empty,
        )

    assert set(histories) == expected_keys
    for key in expected_keys:
        assert histories[key].latest_area == (99 + len(identifiers)) * units.acres


def test_matching_histories_rejects_aliases_split_across_history_layers(
    tmp_path: pathlib.Path,
) -> None:
    index = tests.helpers.factories.peri_scribe.kml.parsing.fire_index([
        tests.helpers.factories.peri_scribe.kml.parsing.fire_index_entry(
            "Example",
            "active",
            identifier="canonical",
            aliases=["alias"],
        ),
    ])
    tests.helpers.factories.peri_scribe.fires.scores.write_fire_index(tmp_path, index)
    empty = tests.helpers.factories.geography.empty_frame()
    points = tests.helpers.factories.peri_scribe.fires.scores.reported_frame([
        ("canonical", "Example", 100),
    ])
    incidents = tests.helpers.factories.peri_scribe.fires.scores.reported_frame([
        ("alias", "Example", 200),
    ])

    histories = peri_scribe.fires.scores.matching_histories(
        tmp_path,
        empty,
        points,
        incidents,
    )

    assert histories == {}


def test_matching_histories_rejects_identifier_and_name_collisions(
    tmp_path: pathlib.Path,
) -> None:
    empty = tests.helpers.factories.geography.empty_frame()
    points = tests.helpers.factories.peri_scribe.fires.scores.reported_frame([
        ("name:Smoke", "Different", 100),
        (None, "Smoke", 200),
        ("other", "Other", 300),
    ])

    histories = peri_scribe.fires.scores.matching_histories(
        tmp_path,
        empty,
        points,
        empty,
    )

    assert set(histories) == {"other"}
    assert histories["other"].latest_area == 300 * units.acres


def test_matching_histories_rebuilds_in_a_fresh_execution(
    tmp_path: pathlib.Path,
) -> None:
    empty = tests.helpers.factories.geography.empty_frame()
    points = tests.helpers.factories.peri_scribe.fires.scores.reported_frame([
        ("example", "Example", 100),
    ])

    with peri_scribe.execution.sharing():
        first = peri_scribe.fires.scores.matching_histories(
            tmp_path,
            empty,
            points,
            empty,
        )
        shared = peri_scribe.fires.scores.matching_histories(
            tmp_path,
            empty,
            points,
            empty,
        )
    with peri_scribe.execution.sharing():
        fresh = peri_scribe.fires.scores.matching_histories(
            tmp_path,
            empty,
            points,
            empty,
        )

    assert first["example"] is shared["example"]
    assert first["example"] is not fresh["example"]
    assert first == fresh


def test_matching_histories_uses_derived_evidence_without_creating_a_missing_index(
    tmp_path: pathlib.Path,
) -> None:
    empty = tests.helpers.factories.geography.empty_frame()
    points = tests.helpers.factories.peri_scribe.fires.scores.reported_frame([
        ("example", "Example", 100),
    ])

    with peri_scribe.execution.sharing():
        histories = peri_scribe.fires.scores.matching_histories(
            tmp_path,
            empty,
            points,
            empty,
        )

    assert histories["example"].latest_area == 100 * units.acres
    assert not peri_scribe.sources.snapshots.fire_index_path(tmp_path).exists()


@pytest.mark.parametrize("shared_keys", [{"first", "second"}, {"first"}])
def test_displayed_areas_preserves_full_and_partial_prepared_history_areas(
    shared_keys: set[str],
) -> None:
    empty = tests.helpers.factories.geography.empty_frame()
    points = tests.helpers.factories.peri_scribe.fires.scores.reported_frame([
        ("first", "First", 100),
        ("second", "Second", 200),
    ])
    histories = {
        key: peri_scribe.areas.prepare_history(
            empty,
            points.iloc[[position]],
        )
        for position, key in enumerate(("first", "second"))
        if key in shared_keys
    }

    areas = peri_scribe.fires.scores.displayed_areas(
        ["first", "second"],
        empty,
        points,
        peri_scribe.fires.identity.group_keys(points),
        histories=histories,
    )

    assert areas == [100 * units.acres, 200 * units.acres]
    assert areas[0] is histories["first"].latest_area


def test_scoring_input_preserves_standalone_areas_when_execution_shares_histories(
    tmp_path: pathlib.Path,
    score_fires_stubs: typing.Callable[
        ...,
        tests.helpers.doubles.peri_scribe.fires.scores.ScoreFiresStubs,
    ],
) -> None:
    points = tests.helpers.factories.peri_scribe.fires.scores.reported_frame([
        ("example", "Example", 100),
    ])
    score_fires_stubs(points=points)
    ordinary = peri_scribe.fires.scores.scoring_input(tmp_path)

    with peri_scribe.execution.sharing():
        shared = peri_scribe.fires.scores.scoring_input(tmp_path)

    assert shared.metrics == ordinary.metrics
