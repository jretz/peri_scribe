"""Real SQLite writer commits at selected reader statement boundaries."""

import dataclasses
import sqlite3

import tests.helpers.factories.peri_scribe.geo.database


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
