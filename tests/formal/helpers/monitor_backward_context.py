"""Connect checked backward selections to actual JSONL context recovery."""

import datetime
import json
import pathlib
import re
import threading

import peri_scribe.monitor.history
import tests.formal.helpers.monitor_context
import tests.helpers.factories.peri_scribe.monitor.status


def replay(state: dict[str, str], directory: pathlib.Path) -> None:
    """Require exact context order from a checked terminal search state.

    Args:
        state: A completed TLC context search with its independent selected indices.
        directory: A temporary directory reused for one complete log at a time.
    """
    pattern = (
        r"\[run \|-> (\d+), important \|-> (TRUE|FALSE), start \|-> (TRUE|FALSE)\]"
    )
    source = state["records"]
    parsed = re.findall(pattern, source)
    assert not re.sub(pattern, "", source).strip("<> ,\n"), source
    now = tests.helpers.factories.peri_scribe.monitor.status.NOW
    values = tuple(
        tests.helpers.factories.peri_scribe.monitor.status.record(
            "Starting command"
            if start == "TRUE"
            else ("Starting phase" if important == "TRUE" else "Progress"),
            run_id=str(run),
            when=now - datetime.timedelta(seconds=len(parsed) - index),
            record=index,
        )
        for index, (run, important, start) in enumerate(parsed, 1)
    )
    path = directory / "2026-09.jsonl"
    path.write_text("".join(json.dumps(record) + "\n" for record in values))
    cutoffs = {
        str(run): now + datetime.timedelta(seconds=1)
        for run in tests.formal.helpers.monitor_context.indices(state["runs"])
    }
    selected = peri_scribe.monitor.history.backward_context(
        path,
        cutoffs,
        threading.Event(),
    )
    if state["pending"] != "{}":
        assert selected is None
        selected = tuple(
            peri_scribe.monitor.history.context_records(
                peri_scribe.monitor.history.records_from(path),
                cutoffs,
                threading.Event(),
            ),
        )
    assert selected is not None
    expected = tuple(int(value) for value in re.findall(r"\d+", state["result"]))
    assert tuple(record["record"] for record in selected) == expected
