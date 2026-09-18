"""Compacted timestamp coverage agrees with every original observation."""

import datetime

import hypothesis
import hypothesis.strategies

import peri_scribe.monitor.history
import peri_scribe.monitor.status
import tests.helpers.factories.peri_scribe.monitor.status


@hypothesis.given(
    offsets=hypothesis.strategies.lists(
        hypothesis.strategies.integers(-170000, 1000000),
        max_size=20,
    ),
    times=hypothesis.strategies.lists(
        hypothesis.strategies.integers(-600, 1200000),
        min_size=1,
        max_size=10,
    ),
)
def test_append_preserves_coverage_independently_of_record_order_and_compaction(
    offsets: list[int],
    times: list[int],
) -> None:
    now = tests.helpers.factories.peri_scribe.monitor.status.NOW
    history = peri_scribe.monitor.history.History()
    timestamps = [now + datetime.timedelta(seconds=offset) for offset in offsets]
    for timestamp in timestamps:
        history = peri_scribe.monitor.history.append(
            history,
            (
                tests.helpers.factories.peri_scribe.monitor.status.record(
                    "Progress",
                    when=timestamp,
                ),
            ),
            now,
        )
    for offset in times:
        observed = now + datetime.timedelta(seconds=offset)
        expected = (
            peri_scribe.monitor.status.Health.GOOD
            if any(
                observed - datetime.timedelta(hours=48) <= timestamp <= observed
                for timestamp in timestamps
            )
            else peri_scribe.monitor.status.Health.BAD
        )
        assert (
            peri_scribe.monitor.status.coverage_metric(history, observed).health
            == expected
        )
