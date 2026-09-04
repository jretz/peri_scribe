"""Shared stubs for the peri_scribe.main command tests."""

from __future__ import annotations

import dataclasses
import pathlib
import typing


if typing.TYPE_CHECKING:
    import peri_scribe.sources.fetching


SAMPLE_LAST_EDIT_TIMESTAMP = 2

# The base directory fetch resolves from ``pathlib.Path.cwd()``, which is mocked to
# this value so snapshots never touch the real filesystem.
BASE_DIRECTORY = pathlib.Path("/fetch")


@dataclasses.dataclass(frozen=True, kw_only=True)
class UpdateKmzStubs:
    """Fetch outcome and recorded step calls for update-kmz tests."""

    fetch_result: peri_scribe.sources.fetching.FetchResult
    fetch_calls: list[tuple[pathlib.Path, int, bool]]
    external_calls: list[tuple[object, pathlib.Path]]
    ensure_boundary_calls: list[pathlib.Path | None]
    history_calls: list[pathlib.Path]
    scores_calls: list[pathlib.Path]
    kmz_calls: list[pathlib.Path]
    report_calls: list[pathlib.Path]


@dataclasses.dataclass(frozen=True, kw_only=True)
class ValidateSourcesStubs:
    """Recorded step calls for validate-sources tests."""

    fetch_complete_calls: list[tuple[pathlib.Path, int]]
    fetch_incremental_calls: list[tuple[pathlib.Path, int]]
    validate_calls: list[pathlib.Path]
    removal_calls: list[pathlib.Path]
