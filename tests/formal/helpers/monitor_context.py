"""Bind recent/context partitions to real parsers, rotation, and reader restoration."""

import compression.zstd
import contextlib
import datetime
import json
import pathlib
import re
import threading

import peri_scribe.monitor.history
import tests.helpers.factories.peri_scribe.monitor.status


HISTORY_COUNT = 1 + 16 + 16**2
STATE_COUNT = 537
RECENT_START = 2


def indices(value: str) -> set[int]:
    """Keep record identities independent of the implementation's event sequence.

    Args:
        value: An exported TLC set of integer identities.

    Returns:
        Its exact members.
    """
    assert value.startswith("{"), value
    assert value.endswith("}"), value
    return {int(item) for item in value[1:-1].split(",") if item.strip()}


def records(value: str) -> tuple[dict[str, object], ...]:
    """Construct timestamped log records from the checked context domain.

    Args:
        value: An exported TLC sequence of timestamp, run, and importance records.

    Returns:
        Concrete log records retaining the model's input identities.
    """
    pattern = r"\[when \|-> (\d+), run \|-> (\d+), important \|-> (TRUE|FALSE)\]"
    parsed = re.findall(pattern, value)
    assert not re.sub(pattern, "", value).strip("<> ,\n"), value
    base = tests.helpers.factories.peri_scribe.monitor.status.NOW
    return tuple(
        tests.helpers.factories.peri_scribe.monitor.status.record(
            "Starting phase" if important == "TRUE" else "Progress",
            phase="fetch",
            run_id=str(run),
            when=base + datetime.timedelta(hours=int(when)),
            record=index,
        )
        for index, (when, run, important) in enumerate(parsed, 1)
    )


def replay_partition(state: dict[str, str]) -> None:
    """Replay every checked partial restoration against the actual filter functions.

    Args:
        state: One checked recent/context partition.
    """
    values = records(state["records"])
    since = tests.helpers.factories.peri_scribe.monitor.status.NOW + datetime.timedelta(
        hours=RECENT_START,
    )
    recent = tuple(peri_scribe.monitor.history.recent_records(values, since))
    assert {int(str(record["record"])) for record in recent} == indices(state["recent"])
    cutoffs = {str(run): since for run in indices(state["checked"])}
    restored = tuple(
        peri_scribe.monitor.history.context_records(values, cutoffs, threading.Event()),
    )
    assert {int(str(record["record"])) for record in restored} == indices(
        state["restored"],
    )


def replay_reader(
    state: dict[str, str],
    directory: pathlib.Path,
    *,
    command_context: bool = False,
) -> None:
    """Restore model context across a monthly compression without reingesting rows.

    Args:
        state: A model's initial partition before context restoration.
        directory: A fresh watched directory for this history.
        command_context: Whether older structural records identify command starts.
    """
    values = records(state["records"])
    recent = indices(state["recent"])
    selected_runs = {str(values[index - 1]["run_id"]) for index in recent}
    expected_context = {
        index
        for index, record in enumerate(values, 1)
        if index not in recent
        and str(record["run_id"]) in selected_runs
        and peri_scribe.monitor.history.important(record)
    }
    if command_context:
        values = tuple(
            dict(record, event="Starting command", command="run")
            if index not in recent and peri_scribe.monitor.history.important(record)
            else record
            for index, record in enumerate(values, 1)
        )
        if expected_context:
            # A found command start must terminate the scan before irrelevant archives.
            (directory / "2026-08.jsonl.zst").write_bytes(b"Unread archive canary")
    path = directory / "2026-09.jsonl"
    path.write_text(
        "".join(
            json.dumps(record) + "\n"
            for record in sorted(
                values,
                key=lambda record: str(record["timestamp"]),
            )
        ),
    )
    now = (
        tests.helpers.factories.peri_scribe.monitor.status.NOW
        + datetime.timedelta(
            hours=RECENT_START,
        )
        + peri_scribe.monitor.history.WINDOW
    )
    with contextlib.closing(peri_scribe.monitor.history.Reader(directory)) as reader:
        history = reader.catch_up(now)
        assert not history.errors
        observed = [
            int(str(event.fields["record"]))
            for run in history.state.runs
            for event in run.events
        ]
        assert expected_context <= set(observed), state
        assert set(observed) <= recent | expected_context, state
        assert len(observed) == len(set(observed)), state
        compressed = path.with_suffix(".jsonl.zst")
        compressed.write_bytes(compression.zstd.compress(path.read_bytes()))
        path.unlink()
        after_rotation = reader.catch_up(now)
        assert after_rotation == history, state
