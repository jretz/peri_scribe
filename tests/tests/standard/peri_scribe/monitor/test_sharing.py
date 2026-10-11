"""Pooling saves immutable metadata while preserving independent JSON records."""

import typing

import pytest

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


@pytest.mark.parametrize(
    "segments",
    [
        None,
        {},
        [5],
        [{"branch": "only"}],
        [{"phase": 1}],
        [{"phase": "fetch", "branch": 1}],
        [{"phase": "fetch", "extra": "keep"}],
        [{"phase": "fetch", "branch": "one", "extra": "keep"}],
        [{"phase": "🔥" * 500}],
    ],
)
def test_phase_metadata_leaves_unfamiliar_or_large_segments_complete(
    segments: object,
) -> None:
    assert peri_scribe.monitor.sharing.phase_metadata(segments) is None
    fields = {"phase_segments": segments}
    assert dict(peri_scribe.monitor.sharing.record(fields)) == fields


def test_phase_metadata_preserves_empty_explicit_path() -> None:
    metadata = peri_scribe.monitor.sharing.phase_metadata([])
    assert metadata is not None
    assert metadata.path == ()
    assert metadata.encoded == "[]"


def test_phase_metadata_cache_bounds_retained_metadata() -> None:
    maximum = 512
    peri_scribe.monitor.sharing.metadata_for_key.cache_clear()
    for index in range(600):
        assert peri_scribe.monitor.sharing.phase_metadata([{"phase": str(index)}])
    assert peri_scribe.monitor.sharing.metadata_for_key.cache_info().currsize <= maximum


def test_record_get_materializes_independent_phase_metadata() -> None:
    record = peri_scribe.monitor.sharing.record({
        "event": "Work",
        "phase_segments": [{"phase": "fetch"}],
    })
    first = typing.cast("list[dict[str, object]]", record.get("phase_segments"))
    first[0]["phase"] = "changed"
    assert record.get("phase_segments") == [{"phase": "fetch"}]
    assert record.get("event") == "Work"
    assert record.get("missing", "default") == "default"


def test_record_get_retains_missing_phase_default() -> None:
    record = peri_scribe.monitor.sharing.Record(encoded_fields={})
    assert record.get("phase_segments", "default") == "default"


@pytest.mark.parametrize("ordinary_phase", [False, True])
def test_record_isolates_nested_json_from_sources_and_each_consumer(
    *,
    ordinary_phase: bool,
) -> None:
    nested: dict[str, object] = {"items": [1, {"message": "original"}]}
    original: dict[str, object] = {"event": "Original", "details": nested}
    if ordinary_phase:
        original["phase_segments"] = [{"phase": "fetch"}]
    saved = peri_scribe.monitor.sharing.record(
        original,
        metadata=peri_scribe.monitor.sharing.phase_metadata(
            original.get("phase_segments"),
        ),
    )
    original["event"] = "Changed"
    nested["items"] = []
    inspected = typing.cast("dict[str, object]", saved["details"])
    inspected["items"] = ["changed"]
    assert saved["event"] == "Original"
    assert saved.get("details") == {"items": [1, {"message": "original"}]}
    default = peri_scribe.monitor.sharing.SerializedValue(text="[]")
    assert saved.get("missing", default) is default
