"""Observe command recovery boundaries while every network operation is replaced."""

from __future__ import annotations

import dataclasses
import pathlib
import typing

import peri_scribe.pipeline_state
import peri_scribe.sources.fetching
import peri_scribe.sources.validation


if typing.TYPE_CHECKING:
    import pytest


@dataclasses.dataclass(kw_only=True)
class Collection:
    """Record durable intent visible immediately before an authoritative write."""

    changed: bool = True
    interrupt: bool = False
    pending: list[peri_scribe.pipeline_state.PendingRun] = dataclasses.field(
        default_factory=list,
    )

    def fetch(
        self,
        base_directory: pathlib.Path,
        *,
        year: int,
    ) -> peri_scribe.sources.fetching.FetchResult:
        """Expose the command's marker at the mutation boundary.

        Args:
            base_directory: Isolated application root supplied by the command.
            year: Year whose source files could change.

        Returns:
            A successful controlled collection result.

        Raises:
            RuntimeError: When the source operation is interrupted.
        """
        directory = base_directory / "data" / str(year)
        self.pending.append(peri_scribe.pipeline_state.read_state(directory))
        if self.interrupt:
            message = "interrupted source mutation"
            raise RuntimeError(message)
        return peri_scribe.sources.fetching.FetchResult(
            snapshot_paths=(),
            changed=self.changed,
        )


def configure_validation(
    monkeypatch: pytest.MonkeyPatch,
    collection: Collection,
) -> None:
    """Keep command locking and marker writes real without accessing a service.

    Args:
        monkeypatch: Restore service substitutions after the test.
        collection: Mutation recorder for the command's authoritative source fetch.
    """
    monkeypatch.setattr(
        peri_scribe.sources.fetching,
        "fetch_all_feeds_complete",
        lambda *_args, **_kwargs: (),
    )
    monkeypatch.setattr(
        peri_scribe.sources.fetching,
        "fetch_all_feeds",
        collection.fetch,
    )
    monkeypatch.setattr(
        peri_scribe.sources.validation,
        "validate_complete_sources",
        lambda *_args: (),
    )
