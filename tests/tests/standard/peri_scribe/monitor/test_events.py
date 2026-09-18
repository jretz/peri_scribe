"""Record normalization preserves useful evidence even in incomplete logs."""

import datetime
import json
import typing

import pytest

import peri_scribe.monitor.events
import peri_scribe.phases


@pytest.mark.parametrize("line", ["not JSON", "[]", "null"])
def test_parse_record_keeps_malformed_lines_visible(line: str) -> None:
    assert peri_scribe.monitor.events.parse_record(line)["event"] == line


def test_parse_record_retains_json_fields() -> None:
    assert peri_scribe.monitor.events.parse_record('{"event":"hello"}') == {
        "event": "hello",
    }


@pytest.mark.parametrize("value", [None, "not a timestamp"])
def test_timestamp_ignores_unusable_values(value: object) -> None:
    assert peri_scribe.monitor.events.timestamp(value) is None


def test_timestamp_assumes_utc_for_naive_values() -> None:
    assert peri_scribe.monitor.events.timestamp(
        "2026-09-16T08:00:00",
    ) == datetime.datetime(2026, 9, 16, 8, tzinfo=datetime.UTC)


def test_event_path_retains_inherited_source_identity() -> None:
    parent = (peri_scribe.phases.Segment(phase="collect-feed", branch="alpha"),)
    path = peri_scribe.monitor.events.event_path(
        {"phase_path": "collect-feed.query-features"},
        parent,
    )
    assert path == (*parent, peri_scribe.phases.Segment(phase="query-features"))


def test_event_path_discovers_source_identity() -> None:
    assert peri_scribe.monitor.events.event_path(
        {"phase_path": "collect-feed", "feed": "beta"},
        (),
    ) == (peri_scribe.phases.Segment(phase="collect-feed", branch="beta"),)


def test_event_path_uses_boundaries_without_explicit_paths() -> None:
    parent = (peri_scribe.phases.Segment(phase="fetch"),)
    child = peri_scribe.monitor.events.event_path(
        {"event": "Starting phase", "phase": "unknown-work"},
        parent,
    )
    assert (
        peri_scribe.monitor.events.event_path(
            {"event": "Finished phase", "phase": "unknown-work"},
            child,
        )
        == child
    )


def test_event_path_keeps_messages_inside_open_phase() -> None:
    parent = (peri_scribe.phases.Segment(phase="fetch"),)
    assert peri_scribe.monitor.events.event_path({"event": "work"}, parent) == parent


def test_make_event_supplies_display_defaults() -> None:
    event = peri_scribe.monitor.events.make_event({}, 1, ())
    assert (event.message, event.level) == ("", "info")


def test_parse_record_keeps_nested_mutable_fields_independent() -> None:
    line = json.dumps({
        "event": "test event",
        "phase_segments": [{"phase": "test phase"}],
        "values": [[1, "nested"]],
    })
    first = peri_scribe.monitor.events.parse_record(line)
    second = peri_scribe.monitor.events.parse_record(line)
    assert first == second
    assert first["event"] is second["event"]
    segments = typing.cast("list[dict[str, object]]", first["phase_segments"])
    segments[0]["phase"] = "changed"
    assert second == json.loads(line)


def test_make_event_shares_equal_resolved_paths() -> None:
    fields: dict[str, object] = {"phase_path": "fetch.collect-feed", "feed": "alpha"}
    first = peri_scribe.monitor.events.make_event(fields, 1, ())
    second = peri_scribe.monitor.events.make_event(dict(fields), 2, ())
    assert first.path is second.path
