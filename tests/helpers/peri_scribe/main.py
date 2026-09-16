"""Inspect main behavior with shared test utilities."""

from __future__ import annotations

import collections.abc


CLICK_USAGE_ERROR_EXIT_CODE = 2


def boundary_payload(entry: collections.abc.Mapping[str, object]) -> dict[str, object]:
    """Keep timing assertions focused on execution boundaries.

    Args:
        entry: A captured boundary with independently tested correlation metadata.

    Returns:
        The boundary's operation and timing fields.
    """
    return {
        key: value
        for key, value in entry.items()
        if key not in {"run_id", "process_id", "phase_segments"}
    }
