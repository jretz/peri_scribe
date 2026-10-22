"""Performance charts preserve completion evidence and readable terminal boundaries."""

import datetime

import pytest

import peri_scribe.monitor.history
import peri_scribe.monitor.model
import peri_scribe.monitor.performance
import tests.helpers.factories.peri_scribe.monitor.events
from measurement_units import units


@pytest.mark.parametrize(
    "metadata",
    [
        None,
        2,
        {},
        {"value": 1},
        {"value": "1", "units": "seconds"},
        {"value": True, "units": "seconds"},
        {"value": [1, 2], "units": "seconds"},
        {"value": -1, "units": "seconds"},
        {"value": float("nan"), "units": "seconds"},
        {"value": float("inf"), "units": "seconds"},
        {"value": 1, "units": "meters"},
        {"value": 1, "units": "not-a-unit"},
        {"value": 1, "units": []},
        {"value": 10**1000, "units": "seconds"},
    ],
)
def test_duration_omits_unusable_metadata(metadata: object) -> None:
    assert peri_scribe.monitor.performance.duration(metadata) is None


@pytest.mark.parametrize("value", [0, 1.25])
def test_duration_converts_valid_metadata_to_seconds(value: float) -> None:
    result = peri_scribe.monitor.performance.duration({
        "value": value,
        "units": "minutes",
    })
    assert result == value * units.minutes
    assert result is not None
    assert result.units == units.seconds


def test_prepare_selects_successful_completions_within_inclusive_window() -> None:
    now = datetime.datetime(2026, 10, 22, 12, tzinfo=datetime.UTC)
    since = now - datetime.timedelta(hours=48)
    cases = (
        ("at-start", "completed", since, {"value": 1, "units": "minutes"}),
        ("at-end", "completed", now, {"value": 3, "units": "seconds"}),
        (
            "too-old",
            "completed",
            since - datetime.timedelta(microseconds=1),
            {"value": 1, "units": "seconds"},
        ),
        (
            "future",
            "completed",
            now + datetime.timedelta(microseconds=1),
            {"value": 1, "units": "seconds"},
        ),
        ("failed", "failed", now, {"value": 1, "units": "seconds"}),
        ("invalid", "completed", now, {"value": -1, "units": "seconds"}),
        ("undated", "completed", None, {"value": 1, "units": "seconds"}),
    )
    records = tuple(
        tests.helpers.factories.peri_scribe.monitor.events.record(
            "Finished command",
            run_id=identifier,
            command="run",
            status=status,
            timestamp=when.isoformat() if when else None,
            duration=elapsed,
        )
        for identifier, status, when, elapsed in cases
    )
    state = peri_scribe.monitor.model.append_records(
        peri_scribe.monitor.model.State(),
        records,
    )
    assert peri_scribe.monitor.performance.prepare(state, now) == (
        peri_scribe.monitor.performance.Series(
            command="run",
            samples=(
                peri_scribe.monitor.performance.Sample(
                    finished=since,
                    duration=60 * units.seconds,
                ),
                peri_scribe.monitor.performance.Sample(
                    finished=now,
                    duration=3 * units.seconds,
                ),
            ),
        ),
    )


def test_prepare_groups_all_recent_runs_after_diagnostic_retention_limit() -> None:
    now = datetime.datetime(2026, 10, 22, 12, tzinfo=datetime.UTC)
    history = peri_scribe.monitor.history.append(
        peri_scribe.monitor.history.History(),
        tuple(
            tests.helpers.factories.peri_scribe.monitor.events.record(
                "Finished command",
                run_id=str(index),
                command="run" if index % 2 else "build",
                status="completed",
                timestamp=(now - datetime.timedelta(minutes=index)).isoformat(),
                duration={"value": index, "units": "seconds"},
            )
            for index in range(120)
        ),
        now,
    )
    series = peri_scribe.monitor.performance.prepare(history.state, now)
    assert [item.command for item in series] == ["build", "run"]
    assert [len(item.samples) for item in series] == [60, 60]
    assert series[0].samples[0].finished < series[0].samples[-1].finished


def test_histogram_assigns_internal_boundaries_right_and_maximum_to_last_bin() -> None:
    now = datetime.datetime(2026, 10, 22, tzinfo=datetime.UTC)
    bins = peri_scribe.monitor.performance.histogram(
        tuple(
            peri_scribe.monitor.performance.Sample(
                finished=now,
                duration=value * units.seconds,
            )
            for value in range(9)
        ),
    )
    assert [(item.lower.magnitude, item.upper.magnitude) for item in bins] == [
        (index, index + 1) for index in range(8)
    ]
    assert [item.count for item in bins] == [1, 1, 1, 1, 1, 1, 1, 2]


def test_histogram_keeps_zero_duration_samples_in_first_bin() -> None:
    now = datetime.datetime(2026, 10, 22, tzinfo=datetime.UTC)
    bins = peri_scribe.monitor.performance.histogram(
        (
            peri_scribe.monitor.performance.Sample(
                finished=now,
                duration=0 * units.second,
            ),
        ),
    )
    assert [item.count for item in bins] == [1]
    assert bins[0].lower == 0 * units.seconds
    expected_upper = 0.01 * units.seconds
    assert bins[-1].upper == expected_upper


def test_render_explains_empty_window() -> None:
    assert (
        peri_scribe.monitor.performance.render(
            (),
            datetime.datetime(2026, 10, 22, tzinfo=datetime.UTC),
            80,
        )
        == "No timing data in the last 48 hours."
    )


def test_render_draws_time_series_and_equal_width_histogram_for_each_type() -> None:
    now = datetime.datetime(2026, 10, 22, 12, tzinfo=datetime.UTC)
    series = tuple(
        peri_scribe.monitor.performance.Series(
            command=command,
            samples=tuple(
                peri_scribe.monitor.performance.Sample(
                    finished=now - datetime.timedelta(hours=hours),
                    duration=elapsed * units.seconds,
                )
                for hours, elapsed in ((48, 0), (24, 8), (24, 4), (0, 0))
            ),
        )
        for command in ("run", "build")
    )
    width = 80
    output = peri_scribe.monitor.performance.render(series, now, width)
    assert "run\nDuration\n" in output
    assert "build\nDuration\n" in output
    assert output.count("Histogram") == len(series)
    assert "10-20 05:00 PDT" in output
    assert "10-22 05:00 PDT" in output
    assert "Completion time (Pacific)" in output
    assert all(character in output for character in ("│", "└", "─", "━"))
    assert "●" not in output
    assert "equal-width" not in output
    assert "completed runs" not in output
    assert max(map(len, output.splitlines())) <= width


def test_render_keeps_single_zero_sample_visible_at_narrow_width() -> None:
    now = datetime.datetime(2026, 10, 22, tzinfo=datetime.UTC)
    series = peri_scribe.monitor.performance.Series(
        command="run",
        samples=(
            peri_scribe.monitor.performance.Sample(
                finished=now,
                duration=0 * units.second,
            ),
        ),
    )
    lines = peri_scribe.monitor.performance.render((series,), now, 1).splitlines()
    assert any("─" in line for line in lines if "│" in line)
    assert not any("●" in line for line in lines)
    assert max(map(len, lines)) <= peri_scribe.monitor.performance.MINIMUM_WIDTH


def test_connect_draws_continuous_slopes_in_both_directions() -> None:
    canvas = [[0] * 3 for _ in range(3)]
    peri_scribe.monitor.performance.connect(canvas, (0, 2), (2, 0))
    assert [
        "".join(peri_scribe.monitor.performance.LINE_CHARACTERS[cell] for cell in row)
        for row in canvas
    ] == ["  ╷", " ┌┘", "╶┘ "]
    peri_scribe.monitor.performance.connect(canvas, (0, 0), (2, 2))
    assert all(canvas[row][column] for row, column in ((0, 0), (1, 1), (2, 2)))


def test_histogram_assigns_rounded_internal_edge_to_following_bin() -> None:
    now = datetime.datetime(2026, 10, 22, tzinfo=datetime.UTC)
    bins = peri_scribe.monitor.performance.histogram(
        tuple(
            peri_scribe.monitor.performance.Sample(
                finished=now,
                duration=elapsed * units.seconds,
            )
            for elapsed in (0, 0.195, 0.39, 0.585, 0.78, 0.975, 1.17, 1.365, 1.56)
        ),
    )
    expected_edge = 1.17 * units.seconds
    assert bins[-3].upper == expected_edge
    assert bins[-2].count == 1
    expected_count = 9
    assert sum(item.count for item in bins) == expected_count


def test_render_wraps_empty_message_for_narrow_terminal() -> None:
    output = peri_scribe.monitor.performance.render(
        (),
        datetime.datetime(2026, 10, 22, tzinfo=datetime.UTC),
        24,
    )
    assert (
        max(map(len, output.splitlines()))
        <= peri_scribe.monitor.performance.MINIMUM_WIDTH
    )
    assert output.replace("\n", " ") == ("No timing data in the last 48 hours.")


def test_render_uses_independent_duration_and_histogram_scales_for_each_type() -> None:
    now = datetime.datetime(2026, 10, 22, tzinfo=datetime.UTC)
    series = tuple(
        peri_scribe.monitor.performance.Series(
            command=command,
            samples=tuple(
                peri_scribe.monitor.performance.Sample(
                    finished=now,
                    duration=elapsed * units.seconds,
                )
                for _ in range(count)
            ),
        )
        for command, elapsed, count in (("brief", 1, 1), ("long", 1000, 100))
    )
    sections = tuple(
        peri_scribe.monitor.performance.render((item,), now, 80) for item in series
    )
    combined = peri_scribe.monitor.performance.render(series, now, 80)
    assert all(section in combined for section in sections)
    assert "1 s │" in sections[0]
    assert "[0.99 s, 1 s]" in sections[0]
    assert "1e+03 s │" in sections[1]
    assert "[999.99 s, 1000 s]" in sections[1]
    for section, maximum_count in zip(sections, ("1", "100"), strict=True):
        histogram = section.split("\nHistogram\n")[1]
        assert histogram.split()[-1] == maximum_count
        assert not any(character in histogram for character in "│└─")


@pytest.mark.parametrize(
    ("now", "left", "right"),
    [
        (
            datetime.datetime(2026, 1, 22, 12, tzinfo=datetime.UTC),
            "01-20 04:00 PST",
            "01-22 04:00 PST",
        ),
        (
            datetime.datetime(2026, 3, 9, 12, tzinfo=datetime.UTC),
            "03-07 04:00 PST",
            "03-09 05:00 PDT",
        ),
        (
            datetime.datetime(2026, 11, 2, 12, tzinfo=datetime.UTC),
            "10-31 05:00 PDT",
            "11-02 04:00 PST",
        ),
    ],
)
def test_time_series_labels_pacific_time_across_daylight_saving_changes(
    now: datetime.datetime,
    left: str,
    right: str,
) -> None:
    series = peri_scribe.monitor.performance.Series(
        command="run",
        samples=(
            peri_scribe.monitor.performance.Sample(
                finished=now,
                duration=1 * units.seconds,
            ),
        ),
    )
    output = "\n".join(peri_scribe.monitor.performance.time_series(series, now, 80))
    assert left in output
    assert right in output
    assert "Completion time (Pacific)" in output
