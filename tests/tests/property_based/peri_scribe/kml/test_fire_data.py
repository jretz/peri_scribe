"""Area qualification uses the same evidence and history as the displayed estimate."""

from __future__ import annotations

import re

import hypothesis

import peri_scribe.kml.fire_data
import tests.helpers.strategies.peri_scribe.presentation.selection


@hypothesis.given(
    requests=tests.helpers.strategies.peri_scribe.presentation.selection.filename_requests(),
)
def test_unique_filename_prefix_allocates_distinct_safe_names(
    requests: list[tuple[str | None, str]],
) -> None:
    used: set[str] = set()
    for identifier, name in requests:
        prefix = peri_scribe.kml.fire_data.unique_filename_prefix(
            identifier,
            name,
            frozenset(used),
        )
        assert prefix not in used
        assert re.fullmatch(r"[a-z0-9]+(?:-[a-z0-9]+)*", prefix)
        used.add(prefix)
