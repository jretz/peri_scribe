"""Seeking variable-length log records agrees with an independent timestamp filter."""

import datetime
import io
import json

import hypothesis
import hypothesis.strategies

import peri_scribe.monitor.storage
import tests.helpers.factories.peri_scribe.monitor.status


@hypothesis.given(
    observations=hypothesis.strategies.lists(
        hypothesis.strategies.tuples(
            hypothesis.strategies.integers(min_value=-100, max_value=100),
            hypothesis.strategies.text(max_size=100),
        ),
        max_size=100,
    ),
)
def test_seek_since_matches_timestamp_filter(
    observations: list[tuple[int, str]],
) -> None:
    cutoff = tests.helpers.factories.peri_scribe.monitor.status.NOW
    ordered = sorted(observations)
    records = [
        {
            "timestamp": (cutoff + datetime.timedelta(minutes=minute)).isoformat(),
            "event": message,
        }
        for minute, message in ordered
    ]
    with io.BytesIO(
        "".join(
            json.dumps(record, ensure_ascii=False) + "\n" for record in records
        ).encode(),
    ) as stream:
        peri_scribe.monitor.storage.seek_since(stream, cutoff)
        actual = [json.loads(line) for line in stream]
    assert actual == [
        record
        for (minute, _), record in zip(ordered, records, strict=True)
        if minute >= 0
    ]
