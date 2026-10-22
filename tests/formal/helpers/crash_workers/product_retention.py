"""Expose real cleanup commits to process death without Python cleanup."""

import collections.abc
import contextlib
import sqlite3

import pytest

import spatial_data.product_cache
import tests.formal.helpers.crash_worker
import tests.formal.helpers.product_retention


def run(request: tests.formal.helpers.crash_worker.Request) -> None:
    """Crash before or after independent retirement and compaction boundaries.

    Args:
        request: The isolated seed, crash, or recovery invocation.
    """
    path = request.directory / "products.sqlite"
    if request.phase == "seed":
        tests.formal.helpers.product_retention.seed(path)
        return
    original_retire = spatial_data.product_cache.retire_contexts
    original_compact = spatial_data.product_cache.compact_store

    def retire(
        connection: sqlite3.Connection,
        contexts: collections.abc.Set[str],
    ) -> bool:
        """Observe completed DELETE statements before the real transaction commits.

        Args:
            connection: The owning maintenance transaction.
            contexts: All contexts that must survive retirement.

        Returns:
            Whether production retirement found obsolete contexts.
        """
        retired = original_retire(connection, contexts)
        if request.boundary == "delete":
            request.terminate()
        return retired

    def needs_compaction(connection: sqlite3.Connection, *, retired: bool) -> bool:
        """Observe the committed retirement before page compaction begins.

        Args:
            connection: The committed maintenance connection.
            retired: Whether obsolete contexts were retired.

        Returns:
            True so the small fixture exercises the real compaction operation.
        """
        if request.boundary == "commit":
            request.terminate()
        return True

    def compact(connection: sqlite3.Connection) -> None:
        """Observe actual compaction before connection cleanup runs.

        Args:
            connection: The committed maintenance connection.
        """
        original_compact(connection)
        request.terminate()

    with contextlib.closing(sqlite3.connect(path)) as writer:
        if request.phase == "recover":
            request.record(
                "recovered",
                sorted(tests.formal.helpers.product_retention.rows(writer)),
            )
            return
        with pytest.MonkeyPatch.context() as patch:
            patch.setattr(spatial_data.product_cache, "retire_contexts", retire)
            patch.setattr(
                spatial_data.product_cache,
                "needs_compaction",
                needs_compaction,
            )
            patch.setattr(spatial_data.product_cache, "compact_store", compact)
            spatial_data.product_cache.maintain_store(
                spatial_data.product_cache.Store(
                    path=path,
                    context="context-1",
                    connection=writer,
                    unconditional=False,
                ),
            )
