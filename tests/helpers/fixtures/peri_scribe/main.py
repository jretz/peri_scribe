"""Isolate main tests with explicit fixtures."""

from __future__ import annotations

import datetime
import pathlib
import typing

import click.testing
import pytest
import time_machine

import peri_scribe.fires.differential
import peri_scribe.fires.scores
import peri_scribe.kml.builder
import peri_scribe.logging
import peri_scribe.output
import peri_scribe.pipeline
import peri_scribe.pipeline_state
import peri_scribe.sources.administrative_boundaries
import peri_scribe.sources.fetching
import peri_scribe.sources.full_fetch_state
import peri_scribe.sources.validation
import tests.helpers.doubles.peri_scribe.main
import tests.helpers.factories.peri_scribe.sources.snapshots


@pytest.fixture
def runner(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: pathlib.Path,
) -> click.testing.CliRunner:
    """Keep CLI-created data and logs inside the test's temporary directory.

    Args:
        monkeypatch: Replace dependencies and restore them after the test.
        tmp_path: Isolated directory for this test's files.

    Returns:
        A runner whose default year directory is isolated from the repository.
    """
    monkeypatch.chdir(tmp_path)
    return click.testing.CliRunner()


@pytest.fixture
def current_year(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: pathlib.Path,
) -> typing.Iterator[None]:
    """Fix the working directory and freeze the current year at 2026.

    Args:
        monkeypatch: Replace dependencies and restore them after the test.
        tmp_path: Isolated directory for this test's files.

    Yields:
        Control while the working directory and current year are isolated.
    """
    monkeypatch.setattr(
        pathlib.Path,
        "cwd",
        staticmethod(
            lambda: (
                tests.helpers.factories.peri_scribe.sources.snapshots.BASE_DIRECTORY
            ),
        ),
    )
    append_monthly_log = peri_scribe.logging.append_monthly_log
    monkeypatch.setattr(
        peri_scribe.logging,
        "append_monthly_log",
        lambda _directory, entry: append_monthly_log(tmp_path / "logs", entry),
    )
    with time_machine.travel(
        datetime.datetime(2026, 1, 1, tzinfo=datetime.UTC),
        tick=False,
    ):
        yield


@pytest.fixture
def run_stubs(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: pathlib.Path,
) -> typing.Callable[..., tests.helpers.doubles.peri_scribe.main.RunStubs]:
    """Install step stubs for the run command.

    Args:
        monkeypatch: The fixture used to replace pipeline steps and state paths.
        tmp_path: The isolated directory for recovery state and the run lock.

    Returns:
        A callable taking whether the fetch changed something, whether the evacuations
        were replaced, and the stored full-fetch state, and returning the installed
        fetch outcome and the lists recording each step's calls.
    """

    def install(
        *,
        changed: bool,
        evacuations_changed: bool = False,
        stored_state: (
            peri_scribe.sources.full_fetch_state.FullFetchState | None
        ) = None,
    ) -> tests.helpers.doubles.peri_scribe.main.RunStubs:
        """Isolate pipeline stages and capture their invocations.

        Args:
            changed: Whether source collection reports changed fire observations.
            evacuations_changed: Whether evacuation contents differ across the simulated
                fetch.
            stored_state: Previously recorded full-fetch checkpoint, or None if absent.

        Returns:
            The configured fetch outcome and captured pipeline calls.
        """
        monkeypatch.setattr(
            peri_scribe.pipeline_state,
            "state_path",
            lambda _year: tmp_path / "run_state.json",
        )
        monkeypatch.setattr(
            peri_scribe.pipeline_state,
            "lock_path",
            lambda _year: tmp_path / ".run.lock",
        )
        stubs = tests.helpers.doubles.peri_scribe.main.RunStubs(
            fetch_result=peri_scribe.sources.fetching.FetchResult(
                snapshot_paths=(),
                changed=changed,
            ),
            fetch_calls=[],
            external_calls=[],
            write_state_calls=[],
            ensure_boundary_calls=[],
            history_calls=[],
            scores_calls=[],
            kmz_calls=[],
            report_calls=[],
        )

        def fetch_all_feeds(
            base_directory: pathlib.Path,
            *,
            year: int,
            full: bool = False,
        ) -> peri_scribe.sources.fetching.FetchResult:
            """Capture fetch options and serve the configured source outcome.

            Args:
                base_directory: Root directory containing data grouped by year.
                year: Collection year supplied by the command.
                full: Whether the fetch must collect the complete layer.

            Returns:
                The source fetch outcome selected for this test.
            """
            stubs.fetch_calls.append((base_directory, year, full))
            return stubs.fetch_result

        monkeypatch.setattr(
            peri_scribe.sources.fetching,
            "fetch_all_feeds",
            fetch_all_feeds,
        )

        def read_state(
            _path: pathlib.Path,
        ) -> peri_scribe.sources.full_fetch_state.FullFetchState | None:
            """Serve the configured full-fetch checkpoint without file access.

            Args:
                _path: File path accepted for compatibility; the configured stub outcome
                    is used.

            Returns:
                The configured checkpoint, or None when none has been stored.
            """
            return stored_state

        def write_state(
            path: pathlib.Path,
            *,
            last_full_fetch: datetime.datetime,
        ) -> None:
            """Capture checkpoint updates for pipeline assertions.

            Args:
                path: Path supplied to the intercepted file operation.
                last_full_fetch: Completion time recorded for the most recent full
                    fetch.
            """
            stubs.write_state_calls.append((path, last_full_fetch))

        monkeypatch.setattr(
            peri_scribe.sources.full_fetch_state,
            "read_state",
            read_state,
        )
        monkeypatch.setattr(
            peri_scribe.sources.full_fetch_state,
            "write_state",
            write_state,
        )
        # The stored evacuations digest is observed before and after the external source
        # fetch; the two observations differ only when the fetch replaced the stored
        # evacuations.
        digests = ["before", "after"] if evacuations_changed else ["same", "same"]

        def stored_evacuations_digest(_year_directory: pathlib.Path) -> str | None:
            """Simulate evacuation contents before and after collection.

            Args:
                _year_directory: Year directory accepted for compatibility with the
                    digest reader.

            Returns:
                The next configured digest, or a stable digest after both reads.
            """
            return digests.pop() if digests else "same"

        monkeypatch.setattr(
            peri_scribe.pipeline,
            "stored_evacuations_digest",
            stored_evacuations_digest,
        )
        monkeypatch.setattr(
            peri_scribe.pipeline,
            "fetch_external_source",
            lambda source, year_directory: stubs.external_calls.append((
                source,
                year_directory,
            )),
        )
        monkeypatch.setattr(
            peri_scribe.sources.administrative_boundaries,
            "ensure_administrative_boundaries",
            lambda year_directory=None: stubs.ensure_boundary_calls.append(
                year_directory,
            ),
        )
        monkeypatch.setattr(
            peri_scribe.fires.differential,
            "write_history_of_differential_geography",
            lambda year, *, unconditional=False: (
                stubs.history_calls.append(year),
                stubs.unconditional_history_calls.append(year)
                if unconditional
                else None,
            ),
        )
        monkeypatch.setattr(
            peri_scribe.fires.scores,
            "score_fires",
            stubs.scores_calls.append,
        )
        monkeypatch.setattr(
            peri_scribe.kml.builder,
            "create_kmz",
            stubs.kmz_calls.append,
        )
        monkeypatch.setattr(
            peri_scribe.pipeline,
            "write_reports",
            stubs.report_calls.append,
        )
        return stubs

    return install


@pytest.fixture
def validate_sources_stubs(
    monkeypatch: pytest.MonkeyPatch,
) -> typing.Callable[
    [tuple[peri_scribe.sources.validation.FeedValidationResult, ...]],
    tests.helpers.doubles.peri_scribe.main.ValidateSourcesStubs,
]:
    """Install step stubs for the validate-sources command.

    Args:
        monkeypatch: Replace dependencies and restore them after the test.

    Returns:
        A callable taking the validation results to serve and returning the recorded
        step calls.
    """

    def install(
        results: tuple[peri_scribe.sources.validation.FeedValidationResult, ...],
    ) -> tests.helpers.doubles.peri_scribe.main.ValidateSourcesStubs:
        """Isolate validation stages and capture their invocations.

        Args:
            results: Validation findings to return from the simulated comparison.

        Returns:
            The captured complete fetch, incremental fetch, and validation calls.
        """
        stubs = tests.helpers.doubles.peri_scribe.main.ValidateSourcesStubs(
            fetch_complete_calls=[],
            fetch_incremental_calls=[],
            validate_calls=[],
            removal_calls=[],
        )

        def fetch_all_feeds_complete(
            base_directory: pathlib.Path,
            *,
            year: int,
        ) -> tuple[pathlib.Path, ...]:
            """Capture complete-fetch requests without collecting remote data.

            Args:
                base_directory: Root directory containing data grouped by year.
                year: Collection year supplied by the command.

            Returns:
                An empty tuple because this stub creates no snapshots.
            """
            stubs.fetch_complete_calls.append((base_directory, year))
            return ()

        def fetch_all_feeds(
            base_directory: pathlib.Path,
            *,
            year: int,
        ) -> peri_scribe.sources.fetching.FetchResult:
            """Capture incremental-fetch requests without collecting remote data.

            Args:
                base_directory: Root directory containing data grouped by year.
                year: Collection year supplied by the command.

            Returns:
                A fetch outcome with no snapshots or source changes.
            """
            stubs.fetch_incremental_calls.append((base_directory, year))
            return peri_scribe.sources.fetching.FetchResult(
                snapshot_paths=(),
                changed=False,
            )

        def validate_complete_sources(
            year_directory: pathlib.Path,
            feeds: object,
        ) -> tuple[peri_scribe.sources.validation.FeedValidationResult, ...]:
            """Capture the validation directory and serve the configured findings.

            Args:
                year_directory: Directory containing the year's source snapshots and
                    derived outputs.
                feeds: Feed configurations to include in the collection or validation.

            Returns:
                The validation findings selected for this test.
            """
            stubs.validate_calls.append(year_directory)
            return results

        monkeypatch.setattr(
            peri_scribe.sources.fetching,
            "fetch_all_feeds_complete",
            fetch_all_feeds_complete,
        )
        monkeypatch.setattr(
            peri_scribe.sources.fetching,
            "fetch_all_feeds",
            fetch_all_feeds,
        )
        monkeypatch.setattr(
            peri_scribe.sources.validation,
            "validate_complete_sources",
            validate_complete_sources,
        )
        monkeypatch.setattr(
            peri_scribe.output,
            "remove_directory_tree",
            stubs.removal_calls.append,
        )
        return stubs

    return install


@pytest.fixture
def validate_sources_setup(monkeypatch: pytest.MonkeyPatch) -> None:
    """Silence log configuration so validate-sources logs can be captured.

    Args:
        monkeypatch: Replace dependencies and restore them after the test.
    """
    monkeypatch.setattr(
        peri_scribe.logging,
        "configure_logging",
        lambda *_args, **_kwargs: None,
    )
