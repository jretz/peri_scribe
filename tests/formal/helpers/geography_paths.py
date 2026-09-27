"""Observe actual geography files, signatures, locks, and ordered layer results."""

from __future__ import annotations

import collections.abc
import contextlib
import dataclasses
import pathlib
import shutil
import typing

import geopandas.testing

import peri_scribe.fires.differential
import peri_scribe.fires.files
import peri_scribe.fires.reuse
import peri_scribe.pipeline_state
import tests.formal.helpers.paths
import tests.formal.helpers.tlc
import tests.helpers.factories.peri_scribe.fires.derived_layers


if typing.TYPE_CHECKING:
    import pytest

    import spatial_data.layers


type ReaderProjection = tuple[int, int, int, int, int, bool, bool, tuple[int, ...]]


@dataclasses.dataclass(kw_only=True)
class Files:
    """Canonical GeoPackages bind symbolic revisions to exact checksums."""

    directory: pathlib.Path
    templates: pathlib.Path
    checksums: dict[str, int]
    parents: dict[str, int]

    @property
    def paths(self) -> tuple[pathlib.Path, pathlib.Path]:
        """Keep full and differential artifacts independently observable.

        Returns:
            Both public production paths in publication order.
        """
        return (
            peri_scribe.fires.files.history_geopackage_path(self.directory),
            peri_scribe.fires.differential.differential_geopackage_path(self.directory),
        )

    def revision(self, path: pathlib.Path) -> int:
        """Exact checksums prevent incomplete bytes from being called a revision.

        Args:
            path: The independently published GeoPackage.

        Returns:
            Its complete revision, with zero also denoting absent reader input.
        """
        return (
            self.checksums[peri_scribe.fires.reuse.file_digest(path)]
            if path.exists()
            else 0
        )

    def write(
        self,
        path: pathlib.Path,
        layers: list[spatial_data.layers.LayerData],
    ) -> None:
        """Use real prewritten layer bytes so a generation has one exact checksum token.

        Args:
            path: The actual production staging destination.
            layers: The production-selected complete layer population.
        """
        revision = int(layers[0].dataframe.revision.iloc[0])
        source = self.templates / str(revision) / "derived" / path.name
        metadata = signature(source)
        assert metadata is not None
        assert tuple(layer.name for layer in layers) == metadata.layers
        for layer in layers:
            expected = geopandas.read_file(source, layer=layer.name)
            geopandas.testing.assert_geodataframe_equal(
                layer.dataframe.reset_index(drop=True),
                expected,
                check_dtype=False,
            )
        shutil.copyfile(source, path)


def signature(path: pathlib.Path) -> peri_scribe.fires.reuse.Signature | None:
    """Raw metadata remains observable even when authentication rejects it.

    Args:
        path: One public geometry artifact.

    Returns:
        Its retained metadata, or None for an absent signature.
    """
    metadata = peri_scribe.fires.reuse.signature_path(path)
    return (
        None
        if not metadata.exists()
        else (
            peri_scribe.fires.reuse.Signature.model_validate_json(
                metadata.read_bytes(),
            )
        )
    )


def templates(directory: pathlib.Path) -> tuple[dict[str, int], dict[str, int]]:
    """Create complete fixtures once; later writes retain their exact byte identity.

    Args:
        directory: Isolated root for all canonical geographic generations.

    Returns:
        Exact checksum and differential-parent identities for three complete revisions.
    """
    checksums, parents = {}, {}
    for revision in range(3):
        root = directory / str(revision)
        tests.helpers.factories.peri_scribe.fires.derived_layers.publish_pair(
            root,
            revision,
        )
        for path in (
            peri_scribe.fires.files.history_geopackage_path(root),
            peri_scribe.fires.differential.differential_geopackage_path(root),
        ):
            checksums[peri_scribe.fires.reuse.file_digest(path)] = revision
        generation = peri_scribe.fires.differential.differential_generation(
            peri_scribe.fires.files.history_geopackage_path(root),
            root,
        )
        assert generation is not None
        parents[generation] = revision
    return checksums, parents


def reader_contract(
    graph: tests.formal.helpers.tlc.Graph,
    *,
    tolerant: bool,
) -> tests.formal.helpers.paths.Contract[ReaderProjection]:
    """Keep locks and read results visible; authentication is an internal decision.

    Args:
        graph: The full checked reader/writer transition graph.
        tolerant: The concrete caller's missing-pair policy.

    Returns:
        An execution contract retaining actual lock, file, and read ordering.
    """
    return tests.formal.helpers.paths.Contract(
        graph=graph,
        values={
            identifier: (
                int(state["full"]),
                int(state["differential"]),
                int(state["fullSignature"]),
                int(state["differentialSignature"]),
                int(state["parent"]),
                state["writer"] == "TRUE",
                state["reader"] == "TRUE",
                tuple(
                    int(value.strip())
                    for value in state["result"][2:-2].split(",")
                    if value.strip()
                ),
            )
            for identifier, state in graph.states.items()
            if (state["tolerant"] == "TRUE") == tolerant
        },
        actions={
            edge: edge.action for edges in graph.outgoing.values() for edge in edges
        },
        internal=frozenset({
            "Authenticate",
            "WriteFull",
            "SignFull",
            "WriteDifferential",
            "SignDifferential",
        }),
    )


@dataclasses.dataclass(kw_only=True)
class Reader:
    """A continuous observer follows one concrete publication/read history."""

    files: Files
    checked: tests.formal.helpers.paths.Contract[ReaderProjection]
    writer: bool = False
    reader: bool = False
    results: tuple[int, ...] = ()
    execution: tests.formal.helpers.paths.Path[ReaderProjection] | None = None

    def snapshot(self) -> ReaderProjection:
        """Retain raw signatures separately from the files they claim to authenticate.

        Returns:
            Physical identities, held locks, and already returned layer values.
        """
        full, differential = self.files.paths
        first, second = signature(full), signature(differential)
        return (
            self.files.revision(full),
            self.files.revision(differential),
            0 if first is None else self.files.checksums[first.checksum],
            0 if second is None else self.files.checksums[second.checksum],
            0
            if second is None
            else self.files.parents[typing.cast("str", second.generation)],
            self.writer,
            self.reader,
            self.results,
        )

    def observe(self, action: str | None = None) -> None:
        """Only the actual operation may consume its corresponding checked edge.

        Args:
            action: Explicit lock/read event, or None for a public file mutation.
        """
        value = self.snapshot()
        if self.execution is None:
            self.execution = self.checked.start(value)
        else:
            self.execution = (
                self.execution.observe(value)
                if action is None
                else (self.execution.transition(action, value))
            )

    def install(self, patch: pytest.MonkeyPatch) -> None:
        """Preserve real locks and reads while checking every visible effect.

        Args:
            patch: The isolated observer scope.
        """
        original_lock = peri_scribe.pipeline_state.read_lock
        original_read = peri_scribe.fires.reuse.read_published_layer
        original_replace = pathlib.Path.replace
        paths = set(self.files.paths)
        paths.update(
            peri_scribe.fires.reuse.signature_path(path) for path in self.files.paths
        )

        @contextlib.contextmanager
        def lock(directory: pathlib.Path) -> collections.abc.Iterator[bool]:
            """A failed acquisition cannot silently enter the model's reader phase.

            Args:
                directory: The production-selected year.

            Yields:
                The real operating-system lock result.
            """
            assert directory == self.files.directory
            acquired = False
            try:
                with original_lock(directory) as acquired:
                    if acquired:
                        self.reader = True
                        self.observe("AcquireReader")
                    yield acquired
            finally:
                if acquired:
                    self.reader = False
                    self.observe("Return")

        def read(path: pathlib.Path, layer: str) -> geopandas.GeoDataFrame:
            """Observe returned rows only after the real authenticated file read.

            Args:
                path: The chosen public artifact.
                layer: The requested layer.

            Returns:
                The real normalized frame.
            """
            with peri_scribe.pipeline_state.run_lock(self.files.directory) as acquired:
                assert not acquired
            result = original_read(path, layer)
            assert len(result) == 1
            self.results += (int(result.revision.iloc[0]),)
            self.observe("Read")
            return result

        def replace(path: pathlib.Path, target: pathlib.Path) -> pathlib.Path:
            """Metadata cannot be silently reordered before its authenticated bytes.

            Args:
                path: The complete staged file.
                target: Its public destination.

            Returns:
                The actual atomic replacement result.
            """
            result = original_replace(path, target)
            if target in paths:
                self.observe()
            return result

        patch.setattr(peri_scribe.pipeline_state, "read_lock", lock)
        patch.setattr(peri_scribe.fires.reuse, "read_published_layer", read)
        patch.setattr(pathlib.Path, "replace", replace)
