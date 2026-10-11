"""Compare byte-level log searches with the proved boundary and window definitions."""

import compression.zstd
import contextlib
import dataclasses
import datetime
import io
import itertools
import json
import pathlib

import peri_scribe.log_reading
import peri_scribe.monitor.history
import tests.formal.helpers.oracle


EPOCH = datetime.datetime(2026, 9, 1, tzinfo=datetime.UTC)


@dataclasses.dataclass(frozen=True, kw_only=True)
class SearchCase:
    """Preserve byte sizes separately from timestamps and semantic record selection."""

    lines: tuple[bytes, ...]
    times: tuple[int | None, ...]
    included: tuple[bool, ...]
    cutoff: int
    upper: int | None
    partial: bytes

    def request(self) -> str:
        """Send exact byte lengths and declared timestamp meanings to Lean.

        Returns:
            The executable proof oracle request.
        """
        body = ";".join(
            f"{len(line)}:{'-' if time is None else time}:{int(included)}"
            for line, time, included in zip(
                self.lines,
                self.times,
                self.included,
                strict=True,
            )
        )
        return (
            f"{self.cutoff}|{'-' if self.upper is None else self.upper}|"
            f"{len(self.partial)}|{body}"
        )


def line(number: int, time: int | None, layout: int, *, included: bool) -> bytes:
    """Build varied complete records whose byte offsets cannot be inferred from indices.

    Args:
        number: The record's occurrence index.
        time: Declared timestamp, or an undated diagnostic.
        layout: Padding, encoding, and timestamp representation variation.
        included: Whether the downstream filter admits this record.

    Returns:
        Complete UTF-8 JSON with misleading nested/string timestamps and one newline.
    """
    value: dict[str, object] = {
        "nested": {"timestamp": "2040-01-01"},
        "message": 'braces } [ and escaped "timestamp": "2099" 🔥'
        + ("é🧭" * ((number + 1) * (layout + 1) ** 3)),
        "take": included,
        "number": number,
        "run_id": str(number),
        "event": f"Observation {number}",
    }
    if time is not None:
        timestamp = EPOCH + datetime.timedelta(seconds=time)
        if layout % 2:
            timestamp = timestamp.astimezone(
                datetime.timezone(datetime.timedelta(hours=-7)),
            )
        value["timestamp"] = timestamp.isoformat()
    elif layout % 2:
        value["timestamp"] = "unparseable diagnostic time"
    return (
        json.dumps(value, ensure_ascii=layout == 0, separators=(",", ":")) + "\n"
    ).encode()


def cases() -> tuple[SearchCase, ...]:
    """Cover ordered dated records and arbitrary undated positions and byte layouts.

    Returns:
        Exhaustive timestamp histories with several representative physical encodings.
    """
    result = []
    for length in range(5):
        for times in itertools.product((None, 0, 1, 2), repeat=length):
            dated = tuple(time for time in times if time is not None)
            if dated != tuple(sorted(dated)):
                continue
            for layout, cutoff, unfinished in itertools.product(
                range(3),
                range(4),
                range(2),
            ):
                included = tuple(
                    layout != 1 or index % 2 == 0 for index in range(length)
                )
                lines = tuple(
                    line(index, time, layout, included=included[index])
                    for index, time in enumerate(times)
                )
                result.append(
                    SearchCase(
                        lines=lines,
                        times=times,
                        included=included,
                        cutoff=cutoff,
                        upper=None if layout == 0 else cutoff + layout - 1,
                        partial=b'{"timestamp":"2040-01-01","unfinished":'
                        if unfinished
                        else b"",
                    ),
                )
    return tuple(result)


def selected(line: bytes) -> bool:
    """Match the lightweight production inclusion boundary before timestamp parsing.

    Args:
        line: An encoded log record.

    Returns:
        Whether the record requests inclusion.
    """
    return b'"take":true' in line


def verify(case: SearchCase, result: tuple[int, ...], directory: pathlib.Path) -> None:
    """Check the actual prefix seek and both actual log-reading storage formats.

    Args:
        case: One semantic history and its exact byte layout.
        result: Lean's exact offset and plain/compressed window occurrence indices.
        directory: Separate storage-format directories for independent seek queries.
    """
    offset, searched, count, *remaining = result
    assert searched == offset
    plain_indices = remaining[:count]
    compressed_count, *compressed_indices = remaining[count:]
    assert len(compressed_indices) == compressed_count
    contents = b"".join(case.lines) + case.partial
    since = EPOCH + datetime.timedelta(seconds=case.cutoff)
    upper = (
        None if case.upper is None else EPOCH + datetime.timedelta(seconds=case.upper)
    )
    with io.BytesIO(contents) as stream:
        peri_scribe.log_reading.seek_since(stream, since)
        assert stream.tell() == offset, (case, offset, stream.tell())
        assert stream.read() == contents[offset:]
    plain = directory / "plain" / "log.jsonl"
    plain.write_bytes(contents)
    observed = tuple(
        peri_scribe.log_reading.complete_lines(
            plain,
            since=since,
            until=upper,
            include=selected,
        ),
    )
    assert observed == tuple(case.lines[index] for index in plain_indices)
    archive = directory / "compressed" / "log.jsonl.zst"
    middle = len(contents) // 2
    archive.write_bytes(
        compression.zstd.compress(contents[:middle])
        + compression.zstd.compress(contents[middle:]),
    )
    observed_compressed = tuple(
        peri_scribe.log_reading.complete_lines(
            archive,
            since=since,
            until=upper,
            include=selected,
        ),
    )
    assert observed_compressed == tuple(
        case.lines[index] for index in compressed_indices
    )


def replay(directory: pathlib.Path) -> int:
    """Require every sampled Python execution to agree with the compiled proof policy.

    Args:
        directory: Isolated location for real plain and compressed files.

    Returns:
        Number of histories checked in each storage format.
    """
    for name in ("plain", "compressed"):
        (directory / name).mkdir(parents=True)
    histories = cases()
    results = tests.formal.helpers.oracle.evaluate(
        [case.request() for case in histories],
        executable="oracleLogSeeking",
    )
    for case, result in zip(histories, results, strict=True):
        verify(case, result, directory)
    return len(histories)


def replay_monitor(directory: pathlib.Path) -> int:
    """Follow ordered records through the real persistent monitor reader.

    Args:
        directory: Isolated directories for independent histories and storage formats.

    Returns:
        Number of real reader lifetimes checked against Lean's retained occurrences.
    """
    histories = tuple(
        SearchCase(
            lines=tuple(
                line(index, time, 0, included=True) for index, time in enumerate(times)
            ),
            times=times,
            included=(True,) * len(times),
            cutoff=1,
            upper=None,
            partial=b'{"unfinished":',
        )
        for times in itertools.product((None, 0, 1, 2), repeat=3)
        if tuple(time for time in times if time is not None)
        == tuple(sorted(time for time in times if time is not None))
    )
    results = tests.formal.helpers.oracle.evaluate(
        [case.request() for case in histories],
        executable="oracleLogSeeking",
    )
    count = 0
    for index, (case, result) in enumerate(zip(histories, results, strict=True)):
        _, _, plain_count, *remaining = result
        _, *archived = remaining[plain_count:]
        for compressed, expected in (
            (False, remaining[:plain_count]),
            (True, archived),
        ):
            location = directory / f"{index}-{compressed}"
            location.mkdir(parents=True)
            path = location / ("2026-09.jsonl.zst" if compressed else "2026-09.jsonl")
            content = b"".join(case.lines) + case.partial
            path.write_bytes(
                compression.zstd.compress(content) if compressed else content,
            )
            original = path.read_bytes()
            now = (
                EPOCH
                + peri_scribe.monitor.history.WINDOW
                + datetime.timedelta(seconds=1)
            )
            with contextlib.closing(
                peri_scribe.monitor.history.Reader(location),
            ) as reader:
                observed = reader.catch_up(now)
                assert observed.caught_up
                assert not observed.errors
                assert {
                    (run.identifier, event.message)
                    for run in observed.state.runs
                    for event in run.events
                } == {(str(item), f"Observation {item}") for item in expected}
                assert reader.catch_up(now) == observed
            assert path.read_bytes() == original
            count += 1
    return count
