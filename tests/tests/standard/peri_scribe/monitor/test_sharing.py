"""Pooling saves immutable metadata while preserving independent JSON records."""

import typing

import peri_scribe.monitor.sharing


def test_compact_does_not_cache_large_unique_text() -> None:
    value = "long" * peri_scribe.monitor.sharing.MAXIMUM_TEXT_LENGTH
    assert peri_scribe.monitor.sharing.compact(value) is value


def test_record_materializes_independent_complete_phase_metadata() -> None:
    original: dict[str, object] = {
        "event": "Work",
        "phase_segments": [
            {"phase": "fetch", "branch": "one", "extra": {"list": [1, 2]}},
        ],
    }
    first = peri_scribe.monitor.sharing.record(original)
    second = peri_scribe.monitor.sharing.record(dict(original))
    assert dict(first) == original
    assert first == original
    assert len(first) == len(original)
    assert list(first.values()) == list(original.values())
    assert list(first) == list(original)
    segments = typing.cast("list[dict[str, object]]", first["phase_segments"])
    segments[0]["phase"] = "changed"
    assert first == second == original


def test_record_retains_non_json_diagnostic_values() -> None:
    original: dict[str, object] = {"phase_segments": [object()]}
    assert peri_scribe.monitor.sharing.record(original) == original


def test_record_keeps_large_phase_metadata_complete() -> None:
    original: dict[str, object] = {
        "phase_segments": [
            {"phase": "x" * peri_scribe.monitor.sharing.MAXIMUM_PHASE_TEXT_LENGTH},
        ],
    }
    assert dict(peri_scribe.monitor.sharing.record(original)) == original
