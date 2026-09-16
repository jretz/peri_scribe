"""Generate gathering examples with constrained domains."""

from __future__ import annotations

import hypothesis.strategies

import peri_scribe.models
import peri_scribe.report.gathering


def report_sections() -> hypothesis.strategies.SearchStrategy[
    list[tuple[peri_scribe.report.gathering.FireReportEntry, ...]]
]:
    """Exercise repeated identities, ambiguous names, and case-insensitive ordering.

    Returns:
        Report sections with independent copies of the same fire and shared names.
    """
    entry = hypothesis.strategies.builds(
        peri_scribe.report.gathering.FireReportEntry,
        status=hypothesis.strategies.from_type(peri_scribe.models.FireStatus),
        name=hypothesis.strategies.sampled_from([
            "2026-a",
            "2026-b",
            "River",
            "river",
            "Cedar",
            "cedar",
        ]),
        identifier=hypothesis.strategies.one_of(
            hypothesis.strategies.none(),
            hypothesis.strategies.sampled_from(["2026-a", "2026-b"]),
        ),
        score=hypothesis.strategies.one_of(
            hypothesis.strategies.none(),
            hypothesis.strategies.integers(0, 1000),
        ),
    )
    return hypothesis.strategies.lists(
        hypothesis.strategies.lists(entry, max_size=8).map(tuple),
        max_size=5,
    )
