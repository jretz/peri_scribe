"""Replace main dependencies with controlled test doubles."""

from __future__ import annotations

import dataclasses
import datetime
import pathlib
import typing


if typing.TYPE_CHECKING:
    import peri_scribe.sources.fetching


@dataclasses.dataclass(frozen=True, kw_only=True)
class RunStubs:
    """Fetch outcome and recorded step calls for run-command tests."""

    fetch_result: peri_scribe.sources.fetching.FetchResult
    fetch_calls: list[tuple[pathlib.Path, int, bool]]
    external_calls: list[tuple[object, pathlib.Path]]
    write_state_calls: list[tuple[pathlib.Path, datetime.datetime]]
    ensure_boundary_calls: list[pathlib.Path | None]
    history_calls: list[pathlib.Path]
    scores_calls: list[pathlib.Path]
    kmz_calls: list[pathlib.Path]
    report_calls: list[pathlib.Path]
    unconditional_history_calls: list[pathlib.Path] = dataclasses.field(
        default_factory=list,
    )


@dataclasses.dataclass(frozen=True, kw_only=True)
class ValidateSourcesStubs:
    """Recorded step calls for validate-sources tests."""

    fetch_complete_calls: list[tuple[pathlib.Path, int]]
    fetch_incremental_calls: list[tuple[pathlib.Path, int]]
    validate_calls: list[pathlib.Path]
    removal_calls: list[pathlib.Path]


def make_version_lookup_recorder(
    *,
    looked_up_distributions: list[str],
) -> typing.Callable[..., str]:
    """Create a callback with controlled dependencies.

    Capture the distribution name used to retrieve the CLI version.

    Args:
        looked_up_distributions: Shared list recording distribution names used for
            version lookup.

    Returns:
        The callback bound to the supplied dependencies.
    """

    def record_lookup(name: str) -> str:
        """Capture the distribution name used to retrieve the CLI version.

        Args:
            name: Distribution name requested by the CLI version command.

        Returns:
            The fixed version string supplied by this test.
        """
        looked_up_distributions.append(name)
        return "1.2.3"

    return record_lookup
