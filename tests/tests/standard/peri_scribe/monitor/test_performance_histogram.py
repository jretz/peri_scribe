"""Histograms adapt their detail to each duration distribution without adding axes."""

import datetime
import math

import pytest

import peri_scribe.monitor.performance
from measurement_units import units


def test_histogram_adds_detail_for_rich_duration_distributions() -> None:
    now = datetime.datetime(2026, 10, 22, tzinfo=datetime.UTC)
    samples = tuple(
        peri_scribe.monitor.performance.Sample(
            finished=now,
            duration=index * units.seconds,
        )
        for index in range(1600)
    )
    bins = peri_scribe.monitor.performance.histogram(samples)
    assert len(bins) == peri_scribe.monitor.performance.MAXIMUM_HISTOGRAM_BINS
    assert sum(item.count for item in bins) == len(samples)


def test_histogram_limits_detail_to_distinct_observed_durations() -> None:
    now = datetime.datetime(2026, 10, 22, tzinfo=datetime.UTC)
    bins = peri_scribe.monitor.performance.histogram(
        tuple(
            peri_scribe.monitor.performance.Sample(
                finished=now,
                duration=elapsed * units.seconds,
            )
            for elapsed in (1, 2) * 100
        ),
    )
    assert [
        (item.lower.magnitude, item.upper.magnitude, item.count) for item in bins
    ] == [
        (1, 1.5, 100),
        (1.5, 2, 100),
    ]


def test_histogram_uses_the_observed_range_for_clustered_durations() -> None:
    now = datetime.datetime(2026, 10, 22, tzinfo=datetime.UTC)
    samples = tuple(
        peri_scribe.monitor.performance.Sample(
            finished=now,
            duration=(100 + index / 100) * units.seconds,
        )
        for index in range(40)
        for _ in range(40)
    )
    bins = peri_scribe.monitor.performance.histogram(samples)
    expected_count = 39
    assert len(bins) == expected_count
    assert bins[0].lower == 100 * units.seconds
    assert bins[-1].upper.m_as("seconds") == pytest.approx(100.39)
    assert sum(item.count for item in bins) == len(samples)


def test_histogram_does_not_subdivide_below_the_logged_timing_resolution() -> None:
    now = datetime.datetime(2026, 10, 22, tzinfo=datetime.UTC)
    samples = tuple(
        peri_scribe.monitor.performance.Sample(
            finished=now,
            duration=(1 + index / 1000) * units.seconds,
        )
        for index in range(6)
    )
    bins = peri_scribe.monitor.performance.histogram(samples)
    assert len(bins) == 1
    assert bins[0].count == len(samples)
    assert bins[0].lower == 1 * units.second
    assert bins[0].upper.m_as("seconds") == pytest.approx(1.005)


@pytest.mark.parametrize("elapsed", [0, 0.005, 3, 1e100])
def test_histogram_keeps_uniform_durations_in_one_positive_width_interval(
    elapsed: float,
) -> None:
    now = datetime.datetime(2026, 10, 22, tzinfo=datetime.UTC)
    samples = tuple(
        peri_scribe.monitor.performance.Sample(
            finished=now,
            duration=elapsed * units.seconds,
        )
        for _ in range(4)
    )
    bins = peri_scribe.monitor.performance.histogram(samples)
    assert len(bins) == 1
    assert bins[0].lower < bins[0].upper
    assert bins[0].lower <= samples[0].duration <= bins[0].upper
    assert bins[0].count == len(samples)


def test_histogram_reduces_bins_when_float_spacing_would_repeat_edges() -> None:
    now = datetime.datetime(2026, 10, 22, tzinfo=datetime.UTC)
    first = 1e14
    second = math.nextafter(first, math.inf)
    third = math.nextafter(second, math.inf)
    samples = tuple(
        peri_scribe.monitor.performance.Sample(
            finished=now,
            duration=elapsed * units.seconds,
        )
        for elapsed in (first, second, third)
    )
    bins = peri_scribe.monitor.performance.histogram(samples)
    expected_count = 2
    assert len(bins) == expected_count
    assert all(item.lower < item.upper for item in bins)
    assert sum(item.count for item in bins) == len(samples)


def test_histogram_assigns_a_published_internal_edge_to_the_following_bin() -> None:
    now = datetime.datetime(2026, 10, 22, tzinfo=datetime.UTC)
    samples = tuple(
        peri_scribe.monitor.performance.Sample(
            finished=now,
            duration=elapsed * units.seconds,
        )
        for elapsed in (0, 0.1, 0.2, 0.3, 0.4, 0.6, 0.8, 1.17, 1.56)
    )
    bins = peri_scribe.monitor.performance.histogram(samples)
    edge = 1.17 * units.seconds
    containing = [item for item in bins if item.lower == edge]
    assert len(containing) == 1
    assert containing[0].count == 1
    assert sum(item.count for item in bins) == len(samples)


def test_histogram_lines_show_ranges_bars_and_counts_without_axes() -> None:
    now = datetime.datetime(2026, 10, 22, tzinfo=datetime.UTC)
    samples = (
        peri_scribe.monitor.performance.Sample(
            finished=now,
            duration=3 * units.seconds,
        ),
    )
    lines = peri_scribe.monitor.performance.histogram_lines(samples, 80)
    assert lines[0] == "Histogram"
    assert len(lines) == len(peri_scribe.monitor.performance.histogram(samples)) + 1
    assert "[2.99 s, 3 s]" in lines[-1]
    assert "━" in lines[-1]
    assert lines[-1].endswith(" 1")
    assert all(character not in "\n".join(lines) for character in ("│", "└", "─"))
    assert all("runs" not in line.lower() for line in lines)


def test_histogram_lines_keep_clustered_interval_labels_distinguishable() -> None:
    now = datetime.datetime(2026, 10, 22, tzinfo=datetime.UTC)
    samples = tuple(
        peri_scribe.monitor.performance.Sample(
            finished=now,
            duration=(100 + index / 100) * units.seconds,
        )
        for index in range(40)
    )
    lines = peri_scribe.monitor.performance.histogram_lines(samples, 80)
    intervals = [line.split("]")[0].split(")")[0].strip() for line in lines[1:]]
    assert len(set(intervals)) == len(intervals)
    assert intervals[0].startswith("[100 s, 100.049 s")
