"""Calculate independent expected results for gathering tests."""

from __future__ import annotations

import typing


if typing.TYPE_CHECKING:
    import peri_scribe.report.gathering


def same_report_fire(
    first: peri_scribe.report.gathering.FireReportEntry,
    second: peri_scribe.report.gathering.FireReportEntry,
) -> bool:
    """Match canonical identifiers, falling back to names only for unidentified fires.

    Args:
        first: One section's report entry.
        second: Another section's report entry.

    Returns:
        Whether the two entries describe the same fire.
    """
    if first.identifier is not None or second.identifier is not None:
        return first.identifier == second.identifier
    return first.name == second.name
