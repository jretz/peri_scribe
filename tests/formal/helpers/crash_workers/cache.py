"""Preserve real cache persistence across independent interpreter lifetimes."""

import pathlib
import sqlite3
import typing

import pytest

import spatial_data.product_cache
import spatial_data.row_index
import tests.formal.helpers.crash_worker
import tests.formal.helpers.product_cache


def run(request: tests.formal.helpers.crash_worker.Request) -> None:
    """Leave a genuine SQLite transaction open when the process dies.

    Args:
        request: A prepared statement prefix, commit boundary, or fresh cache read.
    """
    path = request.directory / "products.sqlite"
    namespace = tests.formal.helpers.product_cache
    if request.phase == "recover":
        with spatial_data.product_cache.scope(path, "policy"):
            store = spatial_data.product_cache.CURRENT.get()
            assert store is not None
            request.record("recovered", namespace.connection_state(store.connection))
            result = spatial_data.row_index.read(
                namespace.ARTIFACT,
                "history",
                "2" if request.boundary == "commit" and request.after else "1",
            )
            request.record("rows", result)
        return
    original_open = spatial_data.product_cache.open_store
    original_put = spatial_data.product_cache.put
    original_prune = spatial_data.product_cache.prune

    def observe(action: str) -> None:
        """Record statement visibility while the owning transaction is still open.

        Args:
            action: The actual production statement category.
        """
        if request.phase == "seed":
            return
        store = spatial_data.product_cache.CURRENT.get()
        assert store is not None
        request.record("pending", namespace.connection_state(store.connection))
        if request.boundary == action:
            request.terminate()

    def put(family: str, key: str, value: bytes) -> None:
        """Interrupt the real generation writer after a selected completed statement.

        Args:
            family: Manifest or row-payload namespace.
            key: The actual content identity.
            value: Serialized production contents.
        """
        original_put(family, key, value)
        observe(
            "MANIFEST"
            if family == namespace.MANIFEST_NAMESPACE
            else "NEW_PAYLOAD"
            if key == namespace.digest(3)
            else "SHARED_PAYLOAD",
        )

    def prune(family: str, keep_keys: typing.Collection[str]) -> None:
        """Keep deletion inside the same production transaction as its replacement.

        Args:
            family: Payload namespace.
            keep_keys: The new manifest's referenced keys.
        """
        original_prune(family, keep_keys)
        observe("PRUNE")

    class Connection(sqlite3.Connection):
        """Intercept the real commit while retaining SQLite's own recovery journal."""

        def commit(self) -> None:
            """A completed commit and an uncommitted transaction recover differently."""
            if (
                request.phase == "crash"
                and request.boundary == "commit"
                and not request.after
            ):
                request.terminate()
            super().commit()
            if request.phase == "crash" and request.boundary == "commit":
                request.terminate()

    def open_store(target: pathlib.Path) -> sqlite3.Connection:
        """Initialize the production schema, then reopen with commit instrumentation.

        Args:
            target: The test's private database.

        Returns:
            A genuine SQLite connection subclass.
        """
        initialized = original_open(target)
        initialized.close()
        return sqlite3.connect(target, factory=Connection)

    with pytest.MonkeyPatch.context() as patch:
        patch.setattr(spatial_data.product_cache, "open_store", open_store)
        patch.setattr(spatial_data.product_cache, "put", put)
        patch.setattr(spatial_data.product_cache, "prune", prune)
        with spatial_data.product_cache.scope(path, "policy"):
            generation = 1 if request.phase == "seed" else 2
            spatial_data.row_index.store_generation(
                (namespace.MANIFEST_NAMESPACE, namespace.PAYLOAD_NAMESPACE),
                str(generation),
                namespace.COLUMNS,
                namespace.groups(generation),
            )
