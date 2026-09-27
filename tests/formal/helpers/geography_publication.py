"""Exercise real publication, acknowledgment, and recovery as continuous TLC paths."""

from __future__ import annotations

import contextlib
import dataclasses
import itertools
import pathlib
import shutil

import pytest
import structlog

import peri_scribe.fires.differential
import peri_scribe.fires.files
import peri_scribe.fires.generation
import peri_scribe.fires.reuse
import peri_scribe.fires.sources
import peri_scribe.logging
import peri_scribe.pipeline
import peri_scribe.pipeline_stages
import peri_scribe.pipeline_state
import spatial_data.layers
import tests.formal.helpers.geography_paths
import tests.formal.helpers.publication_paths
import tests.formal.helpers.tlc
import tests.helpers.doubles.peri_scribe.pipeline_fetch_recovery
import tests.helpers.factories.peri_scribe.fires.derived_layers


@dataclasses.dataclass(frozen=True, kw_only=True)
class Initial:
    """Curated initial states separate content, signatures, and reuse preconditions."""

    full: int = 0
    differential: int = 0
    full_signature: int = 0
    differential_signature: int = 0
    invalid_version: int | None = None
    incomplete_layers: int | None = None


def cases() -> tuple[Initial, ...]:
    """Cross content/signature mismatch with each independent metadata guard.

    Returns:
        Old, reusable, crossed, stale, wrong-version, and incomplete-layer fixtures.
    """
    valid = Initial(full=1, differential=1, full_signature=1, differential_signature=1)
    return (
        Initial(),
        valid,
        Initial(full=1, full_signature=1),
        Initial(differential=1, differential_signature=1),
        dataclasses.replace(valid, full_signature=0),
        dataclasses.replace(valid, differential_signature=0),
        dataclasses.replace(valid, full=0),
        dataclasses.replace(valid, differential=0),
        *(dataclasses.replace(valid, invalid_version=index) for index in range(2)),
        *(dataclasses.replace(valid, incomplete_layers=index) for index in range(2)),
    )


def initialize(
    observer: tests.formal.helpers.publication_paths.Observer,
    initial: Initial,
) -> None:
    """Prepare only model initial states, then retain every actual mutation.

    Args:
        observer: Fresh continuous execution observer.
        initial: Independently selected bytes and metadata.
    """
    files = observer.files
    for index, (path, revision, signature_revision) in enumerate(
        zip(
            files.paths,
            (initial.full, initial.differential),
            (initial.full_signature, initial.differential_signature),
            strict=True,
        ),
    ):
        path.parent.mkdir(parents=True, exist_ok=True)
        source = files.templates / str(revision) / "derived" / path.name
        shutil.copyfile(source, path)
        metadata_source = (
            files.templates / str(signature_revision) / "derived" / path.name
        )
        signature = tests.formal.helpers.geography_paths.signature(metadata_source)
        assert signature is not None
        if initial.invalid_version == index:
            signature.version += 1
        if initial.incomplete_layers == index:
            signature.layers = signature.layers[:-1]
        peri_scribe.fires.reuse.signature_path(path).write_text(
            signature.model_dump_json(),
        )
    peri_scribe.pipeline_state.require_stages(
        files.directory,
        (peri_scribe.pipeline_stages.Stage.GEOGRAPHY,),
    )
    observer.observe()


def install(
    patch: pytest.MonkeyPatch,
    observer: tests.formal.helpers.publication_paths.Observer,
) -> None:
    """Keep generation reuse and publication real while isolating geometry derivation.

    Args:
        patch: Isolated model-to-implementation bridge.
        observer: Concrete public files and source generation.
    """

    def full(
        directory: pathlib.Path,
        _prepared: object,
        *,
        generation: str,
        unconditional: bool,
    ) -> pathlib.Path:
        """The fixture replaces only full row derivation, preserving actual publication.

        Args:
            directory: Production-selected year.
            _prepared: Unused isolated source preparation result.
            generation: Actual generation selected by the outer reuse policy.
            unconditional: Effective caller policy.

        Returns:
            The actually published full history path.
        """
        assert generation == str(observer.target)
        assert isinstance(unconditional, bool)
        return tests.helpers.factories.peri_scribe.fires.derived_layers.publish_full(
            directory,
            observer.target,
        )

    observer.install(patch)
    patch.setattr(spatial_data.layers, "write_geopackage", observer.files.write)
    patch.setattr(
        peri_scribe.fires.generation,
        "source_key",
        lambda _: str(observer.target),
    )
    patch.setattr(peri_scribe.fires.sources, "prepare_fire_sources", lambda _: None)
    patch.setattr(peri_scribe.fires.files, "write_prepared_full_geography", full)
    patch.setattr(
        peri_scribe.fires.differential,
        "differential_perimeter_dataframe",
        lambda frame, **_kwargs: frame.copy(),
    )
    patch.setattr(peri_scribe.fires.reuse, "read_rows", lambda *_args, **_kwargs: {})
    patch.setattr(
        peri_scribe.logging,
        "log_phase",
        lambda *_args, **_kwargs: contextlib.nullcontext(),
    )
    patch.setattr(peri_scribe.pipeline, "logger", structlog.ReturnLogger())


def invoke(
    observer: tests.formal.helpers.publication_paths.Observer,
    *,
    forced: bool,
) -> None:
    """The real coordinator alone acknowledges the completed geography stage.

    Args:
        observer: Continuous execution and concrete year directory.
        forced: Whether generation-level reuse is disabled.
    """
    peri_scribe.pipeline.run_selected_stages(
        observer.files.directory,
        1,
        1,
        full_fetch_interval=None,
        unconditional=forced,
    )
    observer.observe()


def recover(
    observer: tests.formal.helpers.publication_paths.Observer,
    *,
    forced: bool,
) -> None:
    """Retry from retained files, allowing terminal process exit only without mutation.

    Args:
        observer: The same matcher and actual files from before process loss.
        forced: The unchanged rebuild policy.
    """
    with (
        pytest.raises(
            tests.helpers.doubles.peri_scribe.pipeline_fetch_recovery.ProcessLoss,
        )
        if observer.failure is not None
        else contextlib.nullcontext()
    ):
        invoke(observer, forced=forced)
    assert observer.execution is not None
    if observer.failure is not None:
        assert observer.triggered
        observer.execution = observer.execution.event(
            "Crash",
            terminal_phases=frozenset({'"done"'}),
        )
        if observer.snapshot()[-1]:
            invoke(observer, forced=forced)
    assert not observer.snapshot()[-1]
    assert observer.snapshot()[:2] == (1, 1)


def replay(graph: tests.formal.helpers.tlc.Graph, directory: pathlib.Path) -> int:
    """Each history includes initial recovery followed by a second source generation.

    Args:
        graph: Complete checked publication graph.
        directory: Isolated real artifact and metadata trees.

    Returns:
        Number of complete concrete histories matched from model initialization.
    """
    specifications = [
        (initial, forced, None)
        for initial, forced in itertools.product(cases(), (False, True))
    ]
    specifications.extend(
        (Initial(), forced, (position, after))
        for forced, position, after in itertools.product(
            (False, True),
            range(5),
            (False, True),
        )
    )
    with pytest.MonkeyPatch.context() as patch:
        patch.setattr(peri_scribe.fires.reuse, "derivation_context", lambda _: "reader")
        checksums, parents = tests.formal.helpers.geography_paths.templates(
            directory / "templates",
        )
        contracts = {
            forced: tests.formal.helpers.publication_paths.contract(
                graph,
                forced=forced,
            )
            for forced in (False, True)
        }
        for number, (initial, forced, failure) in enumerate(specifications):
            observer = tests.formal.helpers.publication_paths.Observer(
                files=tests.formal.helpers.geography_paths.Files(
                    directory=directory / "cases" / str(number),
                    templates=directory / "templates",
                    checksums=checksums,
                    parents=parents,
                ),
                checked=contracts[forced],
                failure=failure,
            )
            initialize(observer, initial)
            with patch.context() as observed:
                install(observed, observer)
                recover(observer, forced=forced)
                if forced or initial == Initial():
                    assert set(observer.replacements) == set(range(5))
                if initial == cases()[1] and not forced:
                    assert observer.replacements == [4]
                observer.target = 2
                observer.changing_source = True
                peri_scribe.pipeline_state.require_stages(
                    observer.files.directory,
                    (peri_scribe.pipeline_stages.Stage.GEOGRAPHY,),
                )
                invoke(observer, forced=forced)
                assert observer.snapshot() == (
                    2,
                    2,
                    (2, 2, True, True),
                    (2, 2, True, True),
                    False,
                )
    return len(specifications)
