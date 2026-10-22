"""Quantized charts retain sample counts and equal-width duration intervals."""

import datetime

import hypothesis
import hypothesis.strategies
import pytest

import peri_scribe.monitor.performance
from measurement_units import units


@hypothesis.given(
    elapsed=hypothesis.strategies.lists(
        hypothesis.strategies.floats(
            min_value=0,
            max_value=1e6,
            allow_nan=False,
            allow_infinity=False,
        ),
        min_size=1,
        max_size=40,
    ),
)
def test_histogram_conserves_samples_with_adjacent_equal_width_bins(
    elapsed: list[float],
) -> None:
    now = datetime.datetime(2026, 10, 22, tzinfo=datetime.UTC)
    bins = peri_scribe.monitor.performance.histogram(
        tuple(
            peri_scribe.monitor.performance.Sample(
                finished=now,
                duration=value * units.seconds,
            )
            for value in elapsed
        ),
    )
    assert sum(item.count for item in bins) == len(elapsed)
    assert 0 * units.seconds <= bins[0].lower <= min(elapsed) * units.seconds
    assert bins[-1].upper >= max(elapsed) * units.seconds
    first_width = (bins[0].upper - bins[0].lower).m_as("seconds")
    for item in bins:
        assert (item.upper - item.lower).m_as("seconds") == pytest.approx(first_width)
    assert [item.upper for item in bins[:-1]] == [item.lower for item in bins[1:]]


@hypothesis.given(
    observations=hypothesis.strategies.lists(
        hypothesis.strategies.tuples(
            hypothesis.strategies.integers(min_value=0, max_value=48 * 60),
            hypothesis.strategies.floats(
                min_value=0,
                max_value=1e6,
                allow_nan=False,
                allow_infinity=False,
            ),
        ),
        min_size=1,
        max_size=20,
    ),
    width=hypothesis.strategies.integers(min_value=1, max_value=160),
)
def test_render_fits_available_width_and_preserves_command_name(
    observations: list[tuple[int, float]],
    width: int,
) -> None:
    now = datetime.datetime(2026, 10, 22, tzinfo=datetime.UTC)
    series = peri_scribe.monitor.performance.Series(
        command="run",
        samples=tuple(
            peri_scribe.monitor.performance.Sample(
                finished=now - datetime.timedelta(minutes=minutes),
                duration=elapsed * units.seconds,
            )
            for minutes, elapsed in sorted(observations, reverse=True)
        ),
    )
    output = peri_scribe.monitor.performance.render((series,), now, width)
    assert max(map(len, output.splitlines())) <= max(
        width,
        peri_scribe.monitor.performance.MINIMUM_WIDTH,
    )
    assert output.splitlines()[0] == "run"
    assert "●" not in output


@hypothesis.given(
    maximum=hypothesis.strategies.floats(
        min_value=0,
        max_value=1e6,
        allow_nan=False,
        allow_infinity=False,
    ),
)
def test_histogram_counts_samples_according_to_its_published_intervals(
    maximum: float,
) -> None:
    now = datetime.datetime(2026, 10, 22, tzinfo=datetime.UTC)
    original = tuple(
        peri_scribe.monitor.performance.Sample(
            finished=now,
            duration=(maximum * (index / 8)) * units.seconds,
        )
        for index in range(9)
    )
    edges = peri_scribe.monitor.performance.histogram(original)
    samples = (
        *original,
        *(
            peri_scribe.monitor.performance.Sample(finished=now, duration=item.lower)
            for item in edges
        ),
    )
    bins = peri_scribe.monitor.performance.histogram(samples)
    for index, item in enumerate(bins):
        assert item.count == sum(
            item.lower <= sample.duration
            and (
                sample.duration < item.upper
                or (index == len(bins) - 1 and sample.duration == item.upper)
            )
            for sample in samples
        )
