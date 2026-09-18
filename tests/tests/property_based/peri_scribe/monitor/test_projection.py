"""Cached status agrees with fresh results across varied evidence and clocks."""

import datetime

import hypothesis
import hypothesis.strategies

import peri_scribe.monitor.projection
import peri_scribe.monitor.status
import tests.helpers.factories.peri_scribe.monitor.status


@hypothesis.given(
    offsets=hypothesis.strategies.lists(
        hypothesis.strategies.integers(-170000, 1000),
        min_size=1,
        max_size=8,
    ),
    times=hypothesis.strategies.lists(
        hypothesis.strategies.integers(-600, 190000),
        min_size=2,
        max_size=8,
    ),
)
def test_refresh_matches_uncached_status_for_arbitrary_clock_sequences(
    offsets: list[int],
    times: list[int],
) -> None:
    now = tests.helpers.factories.peri_scribe.monitor.status.NOW
    records = tuple(
        record
        for index, offset in enumerate(offsets)
        for record in (
            *tests.helpers.factories.peri_scribe.monitor.status.failed_run(
                run_id=str(index),
                when=now + datetime.timedelta(seconds=offset),
            ),
            tests.helpers.factories.peri_scribe.monitor.status.finished(
                "reports",
                run_id=f"recovery-{index}",
                when=now + datetime.timedelta(seconds=offset + 20),
            ),
        )
    )
    history = tests.helpers.factories.peri_scribe.monitor.status.history(*records)
    files = tests.helpers.factories.peri_scribe.monitor.status.files()
    snapshot = None
    for offset in times:
        observed = now + datetime.timedelta(seconds=offset)
        snapshot = peri_scribe.monitor.projection.refresh(
            history,
            files,
            observed,
            snapshot,
        )
        assert snapshot.view == peri_scribe.monitor.status.project(
            history,
            files,
            observed,
        )
