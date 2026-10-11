"""Reusing immutable runs preserves arbitrary input histories and bounded memory."""

import collections
import datetime
import typing
import weakref

import peri_scribe.monitor.history
import peri_scribe.monitor.model
import tests.helpers.factories.peri_scribe.monitor.events
import tests.helpers.factories.peri_scribe.monitor.status


if typing.TYPE_CHECKING:
    import pytest


def test_append_normalizes_externally_constructed_history() -> None:
    now = tests.helpers.factories.peri_scribe.monitor.status.NOW
    state = peri_scribe.monitor.model.append_records(
        peri_scribe.monitor.model.State(),
        (
            tests.helpers.factories.peri_scribe.monitor.status.record("First"),
            tests.helpers.factories.peri_scribe.monitor.status.record("Last"),
        ),
    )
    original = peri_scribe.monitor.history.History(state=state)
    result = peri_scribe.monitor.history.append(
        original,
        (
            tests.helpers.factories.peri_scribe.monitor.status.record(
                "Other run",
                run_id="other",
            ),
        ),
        now,
    )
    assert [event.message for event in result.state.runs[0].events] == ["Last"]
    assert [event.message for event in original.state.runs[0].events] == [
        "First",
        "Last",
    ]


def test_append_reuses_unchanged_compacted_runs() -> None:
    now = tests.helpers.factories.peri_scribe.monitor.status.NOW
    original = tests.helpers.factories.peri_scribe.monitor.status.history(
        tests.helpers.factories.peri_scribe.monitor.status.record("Progress"),
    )
    result = peri_scribe.monitor.history.append(
        original,
        (
            tests.helpers.factories.peri_scribe.monitor.status.record(
                "Other run",
                run_id="other",
                when=now + datetime.timedelta(seconds=1),
            ),
        ),
        now,
    )
    assert result.state.runs[0] is original.state.runs[0]


def test_compact_run_cache_does_not_retain_released_history() -> None:
    run = peri_scribe.monitor.history.compact_run(
        tests.helpers.factories.peri_scribe.monitor.events.run({"event": "Progress"}),
    )
    reference = weakref.ref(run)
    del run
    assert reference() is None


def test_compact_run_bounds_cache_and_recomputes_evicted_history(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(peri_scribe.monitor.history, "MAXIMUM_NORMALIZED_RUNS", 1)
    monkeypatch.setattr(
        peri_scribe.monitor.history,
        "NORMALIZED_RUNS",
        collections.OrderedDict(),
    )
    first = peri_scribe.monitor.history.compact_run(
        tests.helpers.factories.peri_scribe.monitor.events.run({"event": "First"}),
    )
    peri_scribe.monitor.history.compact_run(
        tests.helpers.factories.peri_scribe.monitor.events.run({"event": "Second"}),
    )
    assert len(peri_scribe.monitor.history.NORMALIZED_RUNS) == 1
    assert peri_scribe.monitor.history.compact_run(first) == first


def test_compact_run_does_not_trust_reused_object_identity(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    run = tests.helpers.factories.peri_scribe.monitor.events.run(
        {"event": "First"},
        {"event": "Last"},
    )
    other = peri_scribe.monitor.model.Run(identifier="different")
    monkeypatch.setattr(
        peri_scribe.monitor.history,
        "NORMALIZED_RUNS",
        collections.OrderedDict({id(run): weakref.ref(other)}),
    )
    result = peri_scribe.monitor.history.compact_run(run)
    assert [event.message for event in result.events] == ["Last"]


def test_compact_run_preserves_empty_unattributed_run() -> None:
    run = peri_scribe.monitor.model.Run(identifier="empty")
    assert peri_scribe.monitor.history.compact_run(run) == run
