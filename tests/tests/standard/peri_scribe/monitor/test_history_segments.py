"""Health history preserves occurrences when a live month gains sealed archives."""

import contextlib
import json
import pathlib

import peri_scribe.logging
import peri_scribe.monitor.history
import tests.helpers.factories.peri_scribe.monitor.events
import tests.helpers.factories.peri_scribe.monitor.status


def test_reader_catch_up_replays_new_segments_without_duplicating_occurrences(
    tmp_path: pathlib.Path,
) -> None:
    now = tests.helpers.factories.peri_scribe.monitor.status.NOW
    first = tests.helpers.factories.peri_scribe.monitor.status.failed_run(run_id="one")
    second = tests.helpers.factories.peri_scribe.monitor.status.failed_run(run_id="two")
    path = tests.helpers.factories.peri_scribe.monitor.events.write_log(
        tmp_path,
        *first,
    )
    with contextlib.closing(peri_scribe.monitor.history.Reader(path.parent)) as reader:
        assert reader.catch_up(now).state == (
            tests.helpers.factories.peri_scribe.monitor.status.history(*first).state
        )
        peri_scribe.logging.seal_log(path, force=True)
        path.write_text("".join(json.dumps(record) + "\n" for record in second))
        expected = tests.helpers.factories.peri_scribe.monitor.status.history(
            *first,
            *second,
        ).state
        assert reader.catch_up(now).state == expected
        assert reader.catch_up(now).state == expected
        peri_scribe.logging.seal_log(path, force=True)
        assert reader.catch_up(now).state == expected
    with contextlib.closing(peri_scribe.monitor.history.Reader(path.parent)) as reader:
        assert reader.catch_up(now).state == expected
