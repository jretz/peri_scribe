"""Chronological search handles escaping and archives before JSON deserialization."""

import compression.zstd
import io
import json
import pathlib
import unittest.mock

import pytest

import peri_scribe.log_reading
import tests.helpers.factories.peri_scribe.show_latencies.evidence


@pytest.mark.parametrize(
    "fields",
    [
        {
            "nested": {"timestamp": "2040-01-01"},
            "message": 'quoted "timestamp": "2041" }',
            "timestamp": "2026-09-01T12:00:00+00:00",
        },
        {
            "items": ["timestamp", {"timestamp": "2040-01-01"}],
            "timestamp": "2026-09-01T05:00:00-07:00",
        },
        {"timestamp": "2026-09-01T12:00:00"},
    ],
)
def test_line_timestamp_uses_only_the_root_key(fields: dict[str, object]) -> None:
    assert (
        peri_scribe.log_reading.line_timestamp(json.dumps(fields).encode())
        == tests.helpers.factories.peri_scribe.show_latencies.evidence.NOW
    )


@pytest.mark.parametrize(
    "line",
    [
        b"",
        b'{"timestamp": null}',
        b'{"timestamp":"bad"}',
        b'{"message":"timestamp"}',
        b'{"nested":{"timestamp":"2040-01-01"}}',
    ],
)
def test_line_timestamp_tolerates_missing_or_invalid_root_time(line: bytes) -> None:
    assert peri_scribe.log_reading.line_timestamp(line) is None


def test_seek_since_never_deserializes_probes(monkeypatch: pytest.MonkeyPatch) -> None:
    old = b'{"timestamp":"2026-08-31", "broken":}\n'
    recent = b'{"timestamp":"2026-09-01T12:00:00+00:00"}\n'
    with io.BytesIO(old * 10000 + recent) as stream:
        parser = unittest.mock.Mock(side_effect=AssertionError("deserialized probe"))
        monkeypatch.setattr(json, "loads", parser)
        peri_scribe.log_reading.seek_since(
            stream,
            tests.helpers.factories.peri_scribe.show_latencies.evidence.NOW,
        )
        assert stream.read() == recent
    parser.assert_not_called()


@pytest.mark.parametrize("compressed", [True, False])
def test_complete_lines_skips_old_json_and_stops_at_upper_bound(
    tmp_path: pathlib.Path,
    *,
    compressed: bool,
) -> None:
    path = tmp_path / ("2026-09.jsonl.zst" if compressed else "2026-09.jsonl")
    old = b'{"timestamp":"2026-08-31", "broken":}\n' * 10000
    recent = b'{"timestamp":"2026-09-01T12:00:00+00:00"}\n'
    future = b'{"timestamp":"2026-09-02", "broken":}\n'
    contents = old + recent + future + recent
    path.write_bytes(compression.zstd.compress(contents) if compressed else contents)
    now = tests.helpers.factories.peri_scribe.show_latencies.evidence.NOW
    assert tuple(
        peri_scribe.log_reading.complete_lines(path, since=now, until=now),
    ) == (recent,)
    assert list(tmp_path.iterdir()) == [path]


def test_complete_lines_streams_concatenated_frames_and_ignores_partial_tail(
    tmp_path: pathlib.Path,
) -> None:
    path = tmp_path / "2026-09.jsonl.zst"
    path.write_bytes(
        compression.zstd.compress(b'\n{"event":"first"}\n')
        + compression.zstd.compress(b'{"event":"last"}\n{"partial":'),
    )
    assert tuple(peri_scribe.log_reading.complete_lines(path)) == (
        b'{"event":"first"}\n',
        b'{"event":"last"}\n',
    )


def test_complete_lines_preserves_undated_diagnostics(tmp_path: pathlib.Path) -> None:
    path = tmp_path / "2026-09.jsonl"
    path.write_bytes(b'not json\n{"timestamp":"2026-09-01T12:00:00+00:00"}\n')
    now = tests.helpers.factories.peri_scribe.show_latencies.evidence.NOW
    assert tuple(peri_scribe.log_reading.complete_lines(path, until=now)) == (
        b"not json\n",
        b'{"timestamp":"2026-09-01T12:00:00+00:00"}\n',
    )


@pytest.mark.parametrize("compressed", [True, False])
def test_complete_lines_filters_before_timestamp_extraction(
    tmp_path: pathlib.Path,
    monkeypatch: pytest.MonkeyPatch,
    *,
    compressed: bool,
) -> None:
    path = tmp_path / ("2026-09.jsonl.zst" if compressed else "2026-09.jsonl")
    ignored = b'{"timestamp":"2026-09-01T11:00:00+00:00","event":"detail"}\n'
    included = b'{"timestamp":"2026-09-01T12:00:00+00:00","event":"keep"}\n'
    later = b'{"timestamp":"2026-09-02","event":"keep"}\n'
    contents = ignored + included + ignored + later + included
    path.write_bytes(compression.zstd.compress(contents) if compressed else contents)
    timestamp = unittest.mock.Mock(wraps=peri_scribe.log_reading.line_timestamp)
    monkeypatch.setattr(peri_scribe.log_reading, "line_timestamp", timestamp)
    assert tuple(
        peri_scribe.log_reading.complete_lines(
            path,
            until=tests.helpers.factories.peri_scribe.show_latencies.evidence.NOW,
            include=lambda line: b'"event":"keep"' in line,
        ),
    ) == (included,)
    assert timestamp.call_args_list == [
        unittest.mock.call(included),
        unittest.mock.call(later),
    ]


def test_complete_lines_never_reads_an_archive_as_one_buffer(
    tmp_path: pathlib.Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    path = tmp_path / "2026-09.jsonl.zst"
    line = b'{"timestamp":"2026-09-01T12:00:00+00:00"}\n'
    path.write_bytes(compression.zstd.compress(line))
    with compression.zstd.open(path, "rb") as stream:
        bounded = unittest.mock.MagicMock()
        bounded.__enter__.return_value = bounded
        bounded.__iter__.return_value = iter(stream)
        bounded.read.side_effect = AssertionError("unbounded archive read")
        monkeypatch.setattr(
            compression.zstd,
            "open",
            unittest.mock.Mock(return_value=bounded),
        )
        assert tuple(peri_scribe.log_reading.complete_lines(path)) == (line,)
        bounded.read.assert_not_called()
