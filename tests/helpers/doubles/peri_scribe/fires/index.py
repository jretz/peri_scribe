"""Observe per-fire classification work independently of boundary geometry."""

from __future__ import annotations

import dataclasses
import pathlib
import typing


if typing.TYPE_CHECKING:
    import peri_scribe.fires.sources
    import peri_scribe.models


@dataclasses.dataclass(frozen=True, kw_only=True)
class ClassificationRecorder:
    """Record which complete fire histories require classification."""

    classification: peri_scribe.models.FireClassification | None
    calls: list[tuple[str, ...]] = dataclasses.field(default_factory=list)

    def classify(
        self,
        groups: peri_scribe.fires.sources.FireRecordGroups,
        _year_directory: pathlib.Path,
    ) -> dict[int, peri_scribe.models.FireClassification]:
        """Return controlled results for every requested non-complex fire.

        Args:
            groups: The complete evidence for fires requiring classification.
            _year_directory: The isolated boundary dependency directory.

        Returns:
            Requested classifications, or no results when boundaries are unavailable.
        """
        self.calls.append(tuple(fire.name for fire in groups.fires))
        return (
            {}
            if self.classification is None
            else {id(fire): self.classification for fire in groups.fires}
        )


@dataclasses.dataclass(frozen=True, kw_only=True)
class HydrationRecorder:
    """Supply complete histories only for the requested source-summary groups."""

    complete: peri_scribe.fires.sources.FireRecordGroups
    calls: list[tuple[tuple[int, ...], ...]] = dataclasses.field(default_factory=list)

    def hydrate(
        self,
        requested: tuple[tuple[int, ...], ...],
    ) -> peri_scribe.fires.sources.FireRecordGroups:
        """Retain original fire identities when returning selected complete histories.

        Args:
            requested: The source groups whose classifications are unavailable.

        Returns:
            Complete records and the original fire objects for the requested groups.
        """
        self.calls.append(requested)
        fires = dict(zip(self.complete.groups, self.complete.fires, strict=True))
        return dataclasses.replace(
            self.complete,
            groups=requested,
            fires=tuple(fires[group] for group in requested),
        )
