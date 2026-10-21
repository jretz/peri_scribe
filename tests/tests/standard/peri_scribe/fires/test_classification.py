"""Tests for peri_scribe.fires.classification."""

from __future__ import annotations

import concurrent.futures
import pathlib
import threading

import pytest
import shapely.geometry
import structlog

import peri_scribe.fires.classification
import peri_scribe.models
import peri_scribe.perimeters.border_classification
import peri_scribe.perimeters.classification_data
import tests.helpers.doubles.errors
import tests.helpers.doubles.peri_scribe.fires.classification
import tests.helpers.factories.peri_scribe.fires.classification
import tests.helpers.factories.peri_scribe.models


@pytest.mark.parametrize(
    ("available", "expected"),
    [(None, 1), (0, 1), (1, 1), (2, 2), (3, 3), (4, 4), (8, 4), (64, 4)],
)
def test_classification_worker_count_bounds_available_resources(
    monkeypatch: pytest.MonkeyPatch,
    available: int | None,
    expected: int,
) -> None:
    monkeypatch.setattr(
        peri_scribe.fires.classification.os,
        "cpu_count",
        lambda: available,
    )
    assert peri_scribe.fires.classification.classification_worker_count() == expected


def test_classify_fire_sources_returns_empty_without_non_complex_fires() -> None:
    fire = peri_scribe.models.Fire(
        name="Park Fire",
        status=tests.helpers.factories.peri_scribe.models.ACTIVE,
        identifier="parent",
        aliases=frozenset({"parent"}),
    )
    groups = tests.helpers.factories.peri_scribe.fires.classification.record_groups(
        fire=fire,
        complex_identifiers=frozenset({"parent"}),
    )
    assert (
        peri_scribe.fires.classification.classify_fire_sources(
            groups,
            pathlib.Path("/base"),
        )
        == {}
    )


def test_classify_fire_sources_returns_empty_when_boundaries_missing(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    fire = peri_scribe.models.Fire(
        name="Park Fire",
        status=tests.helpers.factories.peri_scribe.models.ACTIVE,
    )

    fail = tests.helpers.doubles.errors.raising_stub(FileNotFoundError("missing"))

    monkeypatch.setattr(
        peri_scribe.perimeters.border_classification,
        "load_boundaries",
        fail,
    )
    with structlog.testing.capture_logs() as captured:
        result = peri_scribe.fires.classification.classify_fire_sources(
            tests.helpers.factories.peri_scribe.fires.classification.record_groups(
                fire=fire,
            ),
            pathlib.Path("/base"),
        )
    assert result == {}
    assert [event["event"] for event in captured] == ["Skipping border classification"]


def test_classify_fire_sources_classifies_each_fire(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    fire = peri_scribe.models.Fire(
        name="Park Fire",
        status=tests.helpers.factories.peri_scribe.models.ACTIVE,
    )
    boundary = peri_scribe.perimeters.classification_data.Boundaries(
        box=shapely.geometry.box(0.0, 0.0, 10.0, 10.0),
        border=shapely.geometry.LineString([(10.0, 0.0), (10.0, 10.0)]),
    )
    classification = peri_scribe.models.FireClassification(
        classification=peri_scribe.models.BorderClassification.INSIDE_CALIFORNIA,
        outside_area_fraction=0.0,
        inside_area_fraction=1.0,
    )
    monkeypatch.setattr(
        peri_scribe.perimeters.border_classification,
        "load_boundaries",
        lambda _base_dir: boundary,
    )
    monkeypatch.setattr(
        peri_scribe.perimeters.border_classification,
        "classify_fire",
        lambda **_kwargs: classification,
    )
    result = peri_scribe.fires.classification.classify_fire_sources(
        tests.helpers.factories.peri_scribe.fires.classification.record_groups(
            fire=fire,
        ),
        pathlib.Path("/base"),
    )
    assert result == {id(fire): classification}


def test_classify_fire_sources_bounds_threads_and_preserves_input_order(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    boundaries = tests.helpers.factories.peri_scribe.fires.classification.boundaries()
    groups = (
        tests.helpers.factories.peri_scribe.fires.classification.many_record_groups(12)
    )
    expected_workers = 4
    workers = (
        tests.helpers.doubles.peri_scribe.fires.classification.ClassificationWorkers(
            boundaries=boundaries,
            barrier=threading.Barrier(expected_workers),
        )
    )
    monkeypatch.setattr(peri_scribe.fires.classification.os, "cpu_count", lambda: 32)
    monkeypatch.setattr(
        peri_scribe.perimeters.border_classification,
        "load_boundaries",
        lambda _year: boundaries,
    )
    monkeypatch.setattr(
        peri_scribe.fires.classification,
        "classify_fire_group",
        workers,
    )
    result = peri_scribe.fires.classification.classify_fire_sources(
        groups,
        pathlib.Path("/base"),
    )
    assert list(result) == [id(fire) for fire in groups.fires]
    assert [item.outside_area_fraction for item in result.values()] == [
        index / 12 for index in range(12)
    ]
    assert workers.completions.index(1) < workers.completions.index(0)
    assert workers.counts == {"active": 0, "peak": expected_workers}
    assert len(workers.threads) == expected_workers
    assert all(not thread.is_alive() for thread in workers.threads)


def test_classify_fire_sources_joins_admitted_workers_before_propagating_failure(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    boundaries = tests.helpers.factories.peri_scribe.fires.classification.boundaries()
    groups = (
        tests.helpers.factories.peri_scribe.fires.classification.many_record_groups(4)
    )
    workers = (
        tests.helpers.doubles.peri_scribe.fires.classification.ClassificationWorkers(
            boundaries=boundaries,
            barrier=threading.Barrier(2),
            fail_first=True,
            hold_second=True,
        )
    )
    monkeypatch.setattr(peri_scribe.fires.classification.os, "cpu_count", lambda: 2)
    monkeypatch.setattr(
        peri_scribe.perimeters.border_classification,
        "load_boundaries",
        lambda _year: boundaries,
    )
    monkeypatch.setattr(
        peri_scribe.fires.classification,
        "classify_fire_group",
        workers,
    )
    with concurrent.futures.ThreadPoolExecutor(max_workers=1) as caller:
        future = caller.submit(
            peri_scribe.fires.classification.classify_fire_sources,
            groups,
            pathlib.Path("/base"),
        )
        try:
            assert workers.second_started.wait(timeout=5)
            assert workers.failed.wait(timeout=5)
            assert not future.done()
        finally:
            workers.release.set()
        with pytest.raises(ValueError, match="Classification worker failed"):
            future.result(timeout=5)
    assert workers.counts == {"active": 0, "peak": 2}
    assert all(not thread.is_alive() for thread in workers.threads)
