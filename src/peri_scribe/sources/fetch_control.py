"""Coordinate durable fetch intent independently of the input providers.

[Pipeline publication](../../../docs/algorithms/pipeline-publication.md)
describes the recovery protocol and its verification.
"""

from __future__ import annotations

import datetime
import typing

import peri_scribe.paths
import peri_scribe.pipeline_state
import peri_scribe.sources.full_fetch_state
import peri_scribe.sources.snapshots


if typing.TYPE_CHECKING:
    import collections.abc
    import pathlib


class FeedCollector(typing.Protocol):
    """Collect configured feeds with the cadence and indexing chosen by the stage."""

    def __call__(
        self,
        base_directory: pathlib.Path,
        /,
        *,
        year: int,
        full: bool,
        build_index: bool = True,
    ) -> peri_scribe.sources.snapshots.FetchResult:
        """Return the actual saved snapshots and whether any input changed."""


class SourceCollector(typing.Protocol):
    """Collect fire sources through the production cadence and failure protocol."""

    def __call__(
        self,
        year_directory: pathlib.Path,
        /,
        *,
        full_fetch_interval: datetime.timedelta | None,
    ) -> tuple[peri_scribe.sources.snapshots.FetchResult, bool]:
        """Return the saved snapshots and whether a scheduled full fetch ran."""


def collect_fire_sources(
    year_directory: pathlib.Path,
    *,
    full_fetch_interval: datetime.timedelta | None,
    fetch: FeedCollector,
    prepare: collections.abc.Callable[[pathlib.Path], None],
    defer_index: bool = False,
) -> tuple[peri_scribe.sources.snapshots.FetchResult, bool]:
    """Preserve full-fetch and failure requirements across publication decisions.

    Args:
        year_directory: The directory holding this year's sources and recovery state.
        full_fetch_interval: How often to force a full fetch, or None.
        fetch: Feed collection and optional indexing operation.
        prepare: Administrative boundary preparation before indexing.
        defer_index: Build the index only after the publication gate accepts updates.

    Returns:
        The collected snapshots and whether a scheduled full fetch was performed.

    Raises:
        SystemExit: If collection fails while the required rebuild remains pending.
    """
    base_directory = peri_scribe.sources.snapshots.base_directory_for_year_directory(
        year_directory,
    )
    year = peri_scribe.paths.year_for_year_directory(year_directory)
    state_file = peri_scribe.sources.full_fetch_state.state_path(year_directory)
    full = False
    if full_fetch_interval is not None:
        stored_state = peri_scribe.sources.full_fetch_state.read_state(state_file)
        current_time = datetime.datetime.now(datetime.UTC)
        last_full_fetch = (
            stored_state.last_full_fetch if stored_state is not None else None
        )
        full = peri_scribe.sources.full_fetch_state.full_fetch_is_due(
            interval=full_fetch_interval,
            current_time=current_time,
            last_full_fetch=last_full_fetch,
        )
    if full:
        peri_scribe.pipeline_state.require_stages(
            year_directory,
            peri_scribe.pipeline_state.DERIVED_STAGES,
            unconditional=True,
        )
    try:
        if defer_index:
            result = fetch(base_directory, year=year, full=full, build_index=False)
        else:
            prepare(year_directory)
            result = fetch(base_directory, year=year, full=full)
    except Exception, SystemExit:
        # A failed feed can follow successful snapshot writes from other feeds.
        peri_scribe.pipeline_state.require_stages(
            year_directory,
            peri_scribe.pipeline_state.DERIVED_STAGES,
        )
        raise
    if full and not defer_index:
        peri_scribe.sources.full_fetch_state.write_state(
            state_file,
            last_full_fetch=datetime.datetime.now(datetime.UTC),
        )
    return result, full


def run_ungated_fetch(
    year_directory: pathlib.Path,
    *,
    full_fetch_interval: datetime.timedelta | None,
    unconditional: bool,
    collect: SourceCollector,
    refresh: collections.abc.Callable[[pathlib.Path], bool],
) -> bool:
    """Record recovery work before changing any source or deferred marker.

    Args:
        year_directory: The directory holding the year's sources and outputs.
        full_fetch_interval: How often to force full collection, or None.
        unconditional: Bypass change-based skipping.
        collect: Fire collection with its production full-fetch protocol.
        refresh: Refresh independently persisted external inputs.

    Returns:
        Whether the selected downstream stages should run.
    """
    previous = peri_scribe.pipeline_state.read_state(year_directory)
    deferred = peri_scribe.pipeline_state.has_deferred_inputs(year_directory)
    peri_scribe.pipeline_state.require_stages(
        year_directory,
        peri_scribe.pipeline_state.DERIVED_STAGES,
    )
    peri_scribe.pipeline_state.clear_deferred_inputs(year_directory)
    result, full = collect(year_directory, full_fetch_interval=full_fetch_interval)
    external_changed = refresh(year_directory)
    if restore_previous_state(
        changed=result.changed,
        external_changed=external_changed,
        full=full,
        deferred=deferred,
    ):
        peri_scribe.pipeline_state.write_state(year_directory, previous)
    return proceed_without_pending(
        changed=result.changed,
        external_changed=external_changed,
        unconditional=unconditional,
    ) or bool(peri_scribe.pipeline_state.read_state(year_directory).remaining)


def restore_previous_state(
    *,
    changed: bool,
    external_changed: bool,
    full: bool,
    deferred: bool,
) -> bool:
    """Restore captured intent only after an unchanged incremental collection.

    Args:
        changed: Whether fire collection saved a changed input.
        external_changed: Whether an independently stored input changed.
        full: Whether scheduled full collection requires a rebuild.
        deferred: Whether earlier inputs still need indexing.

    Returns:
        Whether the captured marker should replace the temporary requirement.
    """
    return not (changed or external_changed or full or deferred)


def proceed_without_pending(
    *,
    changed: bool,
    external_changed: bool,
    unconditional: bool,
) -> bool:
    """Determine whether changed inputs already require downstream work.

    Args:
        changed: Whether fire collection saved a changed input.
        external_changed: Whether an independently stored input changed.
        unconditional: Whether the invocation bypasses change-based skipping.

    Returns:
        Whether to proceed before reading the remaining recovery requirements.
    """
    return changed or external_changed or unconditional
