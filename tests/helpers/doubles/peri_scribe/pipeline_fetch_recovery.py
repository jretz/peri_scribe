"""Control persistent input changes independently of pipeline recovery bookkeeping."""

from __future__ import annotations

import dataclasses
import enum
import pathlib
import typing

import peri_scribe.pipeline
import peri_scribe.pipeline_state
import peri_scribe.sources.fetching


if typing.TYPE_CHECKING:
    import pytest


class ProcessLoss(BaseException):
    """Bypass exception recovery after an input has reached persistent storage."""


class Mutation(enum.StrEnum):
    """Identify independently persisted input families."""

    FIRE = "fire"
    EVACUATIONS = "evacuations"


@dataclasses.dataclass(kw_only=True)
class Scenario:
    """Retain source revisions so a retry truthfully reports no additional changes."""

    directory: pathlib.Path
    changes: frozenset[Mutation] = frozenset()
    interrupt: Mutation | None = None
    calls: list[str] = dataclasses.field(default_factory=list)
    full_fetches: list[bool] = dataclasses.field(default_factory=list)

    def path(self, mutation: Mutation) -> pathlib.Path:
        """Keep fault-injected source output separate from the real run marker.

        Args:
            mutation: The independently written input.

        Returns:
            Its durable file under the isolated source directory.
        """
        return self.directory / "sources" / mutation.value

    def mutate(self, mutation: Mutation) -> bool:
        """Write a revision once, optionally losing the process before acknowledgment.

        Args:
            mutation: The input currently being refreshed.

        Returns:
            Whether this attempt stored a new source revision.

        Raises:
            ProcessLoss: After the selected durable input write.
        """
        self.calls.append(mutation.value)
        path = self.path(mutation)
        changed = mutation in self.changes and not path.exists()
        if changed:
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_text("saved source revision", encoding="utf-8")
            if mutation is self.interrupt:
                raise ProcessLoss
        return changed

    def fetch(
        self,
        _base_directory: pathlib.Path,
        *,
        year: int,
        full: bool = False,
    ) -> peri_scribe.sources.fetching.FetchResult:
        """Return the real collection result type after persistent source mutation.

        Args:
            _base_directory: Root accepted by the production fetch backend.
            year: The requested collection year.
            full: Whether this is a scheduled complete fetch.

        Returns:
            Durable snapshot paths and the truthful change indication.
        """
        assert year == int(self.directory.name)
        self.full_fetches.append(full)
        changed = self.mutate(Mutation.FIRE)
        return peri_scribe.sources.fetching.FetchResult(
            snapshot_paths=(self.path(Mutation.FIRE),) if changed else (),
            changed=changed,
        )

    def refresh(self, _year_directory: pathlib.Path) -> bool:
        """Keep evacuation replacement independent from fire collection success.

        Args:
            _year_directory: Year accepted by the production refresh coordinator.

        Returns:
            Whether this attempt replaced the evacuation revision.
        """
        return self.mutate(Mutation.EVACUATIONS)

    def prepare(self, _year_directory: pathlib.Path) -> None:
        """Observe whether any potentially mutating input preparation has begun.

        Args:
            _year_directory: Year accepted by boundary preparation.
        """
        self.calls.append("prepare")


def install(monkeypatch: pytest.MonkeyPatch, scenario: Scenario) -> None:
    """Retain production run-state I/O, full scheduling, and recovery decisions.

    Args:
        monkeypatch: Isolated replacement scope.
        scenario: Persistent source revisions and selected fault location.
    """
    monkeypatch.setattr(peri_scribe.sources.fetching, "fetch_all_feeds", scenario.fetch)
    monkeypatch.setattr(
        peri_scribe.pipeline,
        "refresh_external_sources",
        scenario.refresh,
    )
    monkeypatch.setattr(
        peri_scribe.pipeline,
        "prepare_administrative_boundaries",
        scenario.prepare,
    )


def fail_state_write(
    _directory: pathlib.Path,
    _state: peri_scribe.pipeline_state.PendingRun,
) -> None:
    """Reject persistence before the pipeline can mutate any inputs.

    Args:
        _directory: The attempted recovery-state directory.
        _state: The attempted durable recovery requirement.

    Raises:
        OSError: The simulated unavailable recovery-state filesystem.
    """
    message = "recovery state unavailable"
    raise OSError(message)


def reject_restoration(
    monkeypatch: pytest.MonkeyPatch,
    original_state: peri_scribe.pipeline_state.PendingRun,
) -> None:
    """Fail only when recovery persistence attempts to relinquish temporary work.

    Args:
        monkeypatch: Isolated replacement scope.
        original_state: The requirements that existed before the unchanged fetch.
    """
    original_write = peri_scribe.pipeline_state.write_state

    def write(
        directory: pathlib.Path,
        state: peri_scribe.pipeline_state.PendingRun,
    ) -> None:
        """Keep actual marker writes except the selected failed restoration.

        Args:
            directory: The real temporary marker directory.
            state: The proposed persistent requirements.

        Raises:
            OSError: When the writer attempts to restore the pre-fetch requirements.
        """
        if state == original_state:
            message = "restoration unavailable"
            raise OSError(message)
        original_write(directory, state)

    monkeypatch.setattr(peri_scribe.pipeline_state, "write_state", write)
