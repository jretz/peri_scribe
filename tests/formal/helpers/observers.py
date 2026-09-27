"""Translate checked observer states without duplicating their policy definitions."""

import contextlib
import dataclasses
import datetime
import json
import pathlib
import re

import peri_scribe.monitor.history
import peri_scribe.monitor.projection
import peri_scribe.monitor.status
import peri_scribe.monitor.storage
import tests.helpers.factories.peri_scribe.monitor.status


BROWSER_CASE_COUNT = 4 * 2 * 5 * 2
CURSOR_STATE_COUNT = 4299
PROJECTION_HISTORY_COUNT = 1 + 8 + 8**2
PROJECTION_CASE_COUNT = PROJECTION_HISTORY_COUNT * 7**2 * 3
NOT_CAUGHT_UP = 2


def sequence(value: str) -> list[str | int]:
    """Preserve TLC's sequence order in the JSON transport for trace replay.

    Args:
        value: A TLC sequence containing only JSON strings or integers.

    Returns:
        Its ordered entries.
    """
    assert value.startswith("<<"), value
    assert value.endswith(">>"), value
    return json.loads("[" + value[2:-2] + "]")


def browser_cases(states: list[dict[str, str]]) -> list[dict[str, object]]:
    """Select complete first refreshes, including both overlapping-poll branches.

    Args:
        states: Every checked state exported by TLC.

    Returns:
        Inputs and expected effects of complete browser refresh transactions.
    """
    return [
        {
            key: json.loads(state[key])
            for key in (
                "kind",
                "initialAge",
                "response",
                "displayed",
                "requests",
                "skipped",
                "age",
            )
        }
        for state in states
        if state["phase"] == '"done"' and state["round"] == "1"
    ]


def replay_reader(state: dict[str, str], directory: pathlib.Path) -> None:
    """Exercise OS handles, partial bytes, rotation, and detectable truncation.

    Args:
        state: A reachable cursor state with its complete action trace.
        directory: An isolated directory for this trace's files.

    Raises:
        AssertionError: If the model introduces an unimplemented action.
    """
    path = directory / "2026-09.jsonl"
    path.write_bytes(b"")
    next_record = 1
    delivered = []
    with contextlib.closing(
        peri_scribe.monitor.storage.Follower(directory, tail=False),
    ) as follower:
        assert not follower.poll().records
        for action in sequence(state["trace"]):
            match action:
                case "write" | "finish":
                    record = json.dumps({"event": "Progress", "record": next_record})
                    content = record if action == "write" else record[1:]
                    with path.open("a") as stream:
                        stream.write(content + "\n")
                    next_record += 1
                case "partial":
                    with path.open("a") as stream:
                        stream.write("{")
                case "poll":
                    batch = follower.poll()
                    assert not batch.errors
                    delivered.extend(record["record"] for record in batch.records)
                case "rotate":
                    path.rename(directory / "retired.jsonl")
                    path.write_bytes(b"")
                case "truncate":
                    path.write_bytes(b"")
                case _:
                    raise AssertionError(action)
    assert delivered == sequence(state["delivered"]), state


def projection_events(value: str) -> tuple[tuple[int, bool], ...]:
    """Reject unexpected state formatting instead of silently omitting evidence.

    Args:
        value: TLC's ordered monitor event records.

    Returns:
        Abstract observation time and success status for each record.
    """
    matches = re.findall(r"\[when \|-> (\d+), successful \|-> (TRUE|FALSE)\]", value)
    remaining = re.sub(
        r"\[when \|-> (\d+), successful \|-> (TRUE|FALSE)\]",
        "",
        value,
    )
    assert not remaining.strip("<> ,\n"), value
    return tuple((int(when), success == "TRUE") for when, success in matches)


def projection_history(
    events: tuple[tuple[int, bool], ...],
) -> peri_scribe.monitor.history.History:
    """Keep history compaction on the implementation path for every model case.

    Args:
        events: Ordered observation times and success status from TLC.

    Returns:
        Real compacted history with one abstract time unit mapped to one day.
    """
    now = tests.helpers.factories.peri_scribe.monitor.status.NOW
    history = peri_scribe.monitor.history.History()
    for index, (when, successful) in enumerate(events):
        record = tests.helpers.factories.peri_scribe.monitor.status.record(
            "Finished phase",
            when=now + datetime.timedelta(days=when),
            phase="fetch",
            run_id=f"run-{index}",
            status="completed" if successful else "failed",
            **({} if successful else {"exception": "Source unavailable"}),
        )
        history = peri_scribe.monitor.history.append(history, (record,), now)
    return history


def replay_projection(
    state: dict[str, str],
    history: peri_scribe.monitor.history.History,
) -> None:
    """Check the modeled contract and the entire cached view against fresh evaluation.

    Args:
        state: A completed TLC projection transition.
        history: Compacted production history for that transition's event sequence.
    """
    now = tests.helpers.factories.peri_scribe.monitor.status.NOW
    diagnostic = int(state["diagnostic"])
    observed = now + datetime.timedelta(days=int(state["currentTime"]))
    previous_time = now + datetime.timedelta(days=int(state["previousTime"]))
    current_history = dataclasses.replace(
        history,
        errors=("Unreadable archive",) if diagnostic == 1 else (),
        caught_up=diagnostic != NOT_CAUGHT_UP,
    )
    files = tests.helpers.factories.peri_scribe.monitor.status.files()
    previous = peri_scribe.monitor.projection.refresh(history, files, previous_time)
    snapshot = peri_scribe.monitor.projection.refresh(
        current_history,
        files,
        observed,
        previous,
    )
    assert snapshot.view == peri_scribe.monitor.status.project(
        current_history,
        files,
        observed,
    ), state
    assert snapshot.view.coverage.health == int(state["coverage"]), state
    source = snapshot.view.metrics[3].target
    expected = int(state["latestSuccess"])
    assert (None if source is None else source.when) == (
        None if expected == -1 else now + datetime.timedelta(days=expected)
    ), state
    expected_periods = [
        (int(start), int(finish))
        for start, finish in re.findall(
            r"\[start \|-> (\d+), finish \|-> (\d+)\]",
            state["periods"],
        )
    ]
    assert history.coverage == tuple(
        peri_scribe.monitor.history.Coverage(
            start=now + datetime.timedelta(days=start),
            end=now + datetime.timedelta(days=finish),
        )
        for start, finish in expected_periods
    ), state


def replay_projection_boundaries(history: peri_scribe.monitor.history.History) -> None:
    """Exercise subsecond expiry, age changes, clock reversal, and artifact changes.

    Args:
        history: A compacted history from the checked model's input domain.
    """
    now = tests.helpers.factories.peri_scribe.monitor.status.NOW
    microsecond = datetime.timedelta(microseconds=1)
    timestamps = {
        event.timestamp
        for run in history.state.runs
        for event in run.events
        if event.timestamp is not None
    } | {now}
    boundaries = {
        timestamp + offset + adjustment
        for timestamp in timestamps
        for offset in (
            datetime.timedelta(),
            datetime.timedelta(minutes=1),
            datetime.timedelta(hours=1),
            datetime.timedelta(hours=6),
            datetime.timedelta(days=1),
            peri_scribe.monitor.history.WINDOW,
        )
        for adjustment in (-microsecond, datetime.timedelta(), microsecond)
    }
    files = tests.helpers.factories.peri_scribe.monitor.status.files()
    changed_files = dataclasses.replace(
        files,
        report=peri_scribe.monitor.status.Output(error="Unreadable output"),
        pending=("reports",),
    )
    snapshot = peri_scribe.monitor.projection.refresh(
        peri_scribe.monitor.history.History(),
        files,
        min(boundaries),
    )
    for observed in (*sorted(boundaries), *sorted(boundaries, reverse=True)):
        for outputs in (files, changed_files, files):
            snapshot = peri_scribe.monitor.projection.refresh(
                history,
                outputs,
                observed,
                snapshot,
            )
            assert snapshot.view == peri_scribe.monitor.status.project(
                history,
                outputs,
                observed,
            )
