"""Real SQLite writer commits at selected reader statement boundaries."""

from __future__ import annotations

import dataclasses
import pathlib
import sqlite3
import typing

import tests.helpers.factories.peri_scribe.geo.database


if typing.TYPE_CHECKING:
    import collections.abc

    import peri_scribe.geo.package


@dataclasses.dataclass(kw_only=True)
class ConcurrentCommit:
    """Make a second connection publish between a cache reader's SELECTs."""

    writer: sqlite3.Connection
    revision: int
    before_select: int
    selects: int = 0
    committed: bool = False

    def __call__(self, statement: str) -> None:
        """Make statement interleavings deterministic without using timing or threads.

        Args:
            statement: SQL that the reader is about to execute.
        """
        if not statement.startswith("SELECT"):
            return
        self.selects += 1
        if self.selects == self.before_select:
            tests.helpers.factories.peri_scribe.geo.database.store(
                self.writer,
                self.revision,
            )
            self.writer.commit()
            self.committed = True


@dataclasses.dataclass(frozen=True, kw_only=True)
class SnapshotReads:
    """Observe real payload hydration while leaving source parsing active."""

    read: collections.abc.Callable[
        ...,
        dict[pathlib.Path, peri_scribe.geo.package.GeopackageContents],
    ]
    calls: list[tuple[pathlib.Path, ...]] = dataclasses.field(default_factory=list)

    def __call__(
        self,
        paths: collections.abc.Sequence[pathlib.Path],
        **kwargs: object,
    ) -> dict[pathlib.Path, peri_scribe.geo.package.GeopackageContents]:
        """Retain the exact requested paths before invoking the real batch reader.

        Args:
            paths: Snapshots whose complete geometry and attributes are requested.
            **kwargs: The real reader's lifetime and fallback options.

        Returns:
            The original reader's complete source contents.
        """
        self.calls.append(tuple(paths))
        return self.read(paths, **kwargs)
