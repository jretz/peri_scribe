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
