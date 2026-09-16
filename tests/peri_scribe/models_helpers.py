"""Generate identifier collections and comparable instants around clock changes."""

from __future__ import annotations

import datetime
import zoneinfo

import hypothesis.strategies


def identifier_collections() -> hypothesis.strategies.SearchStrategy[list[str]]:
    """Exercise all identifier priorities when an iterable can only be consumed once.

    Returns:
        Collections containing unique fire ids, GUIDs, and fallback identifiers.
    """
    return hypothesis.strategies.lists(
        hypothesis.strategies.one_of(
            hypothesis.strategies.from_regex(
                r"20[0-9]{2}-[a-z]{2,4}-[0-9]{1,6}",
                fullmatch=True,
            ),
            hypothesis.strategies.uuids().map(str),
            hypothesis.strategies.text(min_size=1, max_size=12),
        ),
        max_size=12,
    )


@hypothesis.strategies.composite
def clock_change_instants(
    draw: hypothesis.strategies.DrawFn,
) -> tuple[datetime.datetime, datetime.datetime]:
    """Place observations near skipped and repeated local clock hours.

    Args:
        draw: The current example's strategy sampler.

    Returns:
        Two instants expressed in one local zone, ordered by elapsed time.
    """
    base, zone_name = draw(
        hypothesis.strategies.sampled_from([
            (
                datetime.datetime(2026, 3, 8, 9, tzinfo=datetime.UTC),
                "America/Los_Angeles",
            ),
            (
                datetime.datetime(2026, 11, 1, 8, tzinfo=datetime.UTC),
                "America/Los_Angeles",
            ),
            (datetime.datetime(2026, 3, 8, 6, tzinfo=datetime.UTC), "America/New_York"),
            (
                datetime.datetime(2026, 11, 1, 5, tzinfo=datetime.UTC),
                "America/New_York",
            ),
        ]),
    )
    zone = zoneinfo.ZoneInfo(zone_name)
    left = base + datetime.timedelta(
        minutes=draw(hypothesis.strategies.integers(-60, 60)),
    )
    right = left + datetime.timedelta(
        minutes=draw(hypothesis.strategies.integers(0, 180)),
    )
    return left.astimezone(zone), right.astimezone(zone)


@hypothesis.strategies.composite
def clock_change_comparisons(
    draw: hypothesis.strategies.DrawFn,
) -> tuple[datetime.datetime, datetime.datetime, datetime.timedelta]:
    """Compare clock-change observations against a nonnegative time tolerance.

    Args:
        draw: The current example's strategy sampler.

    Returns:
        Two local instants and a tolerance that may straddle their elapsed time.
    """
    left, right = draw(clock_change_instants())
    tolerance = datetime.timedelta(minutes=draw(hypothesis.strategies.integers(0, 180)))
    return left, right, tolerance
