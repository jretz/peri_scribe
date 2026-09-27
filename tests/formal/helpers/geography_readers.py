"""Replay authenticated reader decisions with real GeoPackages and metadata."""

import contextlib
import contextvars
import dataclasses
import itertools
import pathlib
import shutil

import pytest

import peri_scribe.fires.derived_layers
import peri_scribe.fires.differential
import peri_scribe.fires.files
import peri_scribe.fires.reuse
import peri_scribe.pipeline_state
import spatial_data.layers
import tests.formal.helpers.geography_paths
import tests.formal.helpers.paths
import tests.formal.helpers.tlc
import tests.helpers.doubles.peri_scribe.pipeline_fetch_recovery
import tests.helpers.factories.peri_scribe.fires.derived_layers


WRITER_CASES = 20
PUBLICATION_MUTATIONS = 4


@dataclasses.dataclass(frozen=True, kw_only=True)
class ReaderCase:
    """Separate physical file generations from their individually published metadata."""

    full: int
    differential: int
    full_signature: int
    differential_signature: int
    tolerant: bool


def cases(states: list[dict[str, str]]) -> dict[ReaderCase, str]:
    """Retain the checked decision for every input pair and signature combination.

    Args:
        states: Entire checked reader/writer graph.

    Returns:
        Authentication outcomes keyed by input files and metadata.
    """
    result: dict[ReaderCase, str] = {}
    for state in states:
        decision = state["readerPhase"].strip('"')
        if decision not in {"read", "empty", "refused"} or state["result"] != "<<>>":
            continue
        case = ReaderCase(
            full=int(state["full"]),
            differential=int(state["differential"]),
            full_signature=int(state["fullSignature"]),
            differential_signature=int(state["differentialSignature"]),
            tolerant=state["tolerant"] == "TRUE",
        )
        assert case not in result or result[case] == decision
        result[case] = decision
    return result


def copy_generation(
    source: pathlib.Path,
    destination: pathlib.Path,
    generation: int,
) -> None:
    """Preserve exact authenticated bytes while modeling a missing or present file.

    Args:
        source: Template path with a generation directory component.
        destination: Path selected for the real reader.
        generation: Zero denotes absence; positive values choose the template.
    """
    if generation:
        destination.parent.mkdir(parents=True, exist_ok=True)
        shutil.copyfile(source, destination)


def replay(graph: tests.formal.helpers.tlc.Graph, directory: pathlib.Path) -> None:
    """Check real reader acceptance against every authenticated protocol input.

    Args:
        graph: Checked geography reader graph with its actual directed transitions.
        directory: Isolated template and read trees.
    """
    outcomes = cases(list(graph.states.values()))
    expected_count = 162
    assert len(outcomes) == expected_count
    with pytest.MonkeyPatch.context() as patch:
        patch.setattr(peri_scribe.fires.reuse, "derivation_context", lambda _: "reader")
        checksums, parents = tests.formal.helpers.geography_paths.templates(
            directory / "templates",
        )
        contracts = {
            tolerant: tests.formal.helpers.geography_paths.reader_contract(
                graph,
                tolerant=tolerant,
            )
            for tolerant in (False, True)
        }
        for number, (case, decision) in enumerate(outcomes.items()):
            year = directory / "cases" / str(number)
            destinations = (
                peri_scribe.fires.files.history_geopackage_path(year),
                peri_scribe.fires.differential.differential_geopackage_path(year),
            )
            for path, content, signature in zip(
                destinations,
                (case.full, case.differential),
                (case.full_signature, case.differential_signature),
                strict=True,
            ):
                relative = path.relative_to(year)
                copy_generation(
                    directory / "templates" / str(content) / relative,
                    path,
                    content,
                )
                copy_generation(
                    peri_scribe.fires.reuse.signature_path(
                        directory / "templates" / str(signature) / relative,
                    ),
                    peri_scribe.fires.reuse.signature_path(path),
                    signature,
                )
            observer = tests.formal.helpers.geography_paths.Reader(
                files=tests.formal.helpers.geography_paths.Files(
                    directory=year,
                    templates=directory / "templates",
                    checksums=checksums,
                    parents=parents,
                ),
                checked=contracts[case.tolerant],
            )
            observer.observe()
            with patch.context() as observed:
                observer.install(observed)
                if decision == "refused":
                    with pytest.raises((RuntimeError, FileNotFoundError)):
                        peri_scribe.fires.derived_layers.read_derived_layers(
                            year,
                            tolerate_missing=case.tolerant,
                        )
                    continue
                layers = peri_scribe.fires.derived_layers.read_derived_layers(
                    year,
                    tolerate_missing=case.tolerant,
                )
                for frame in (
                    layers.perimeters,
                    layers.points,
                    layers.incidents,
                    layers.differential_perimeters,
                ):
                    if decision == "empty":
                        assert frame.empty
                    else:
                        assert frame.revision.tolist() == [case.full]
        assert writer_prefixes(directory, contracts, checksums, parents) == WRITER_CASES


def publish_prefix(directory: pathlib.Path, prefix: int) -> None:
    """An incomplete writer prefix must end with the selected real process loss.

    Args:
        directory: The isolated production year.
        prefix: Count of complete public-file replacements before interruption.
    """
    with (
        pytest.raises(
            tests.helpers.doubles.peri_scribe.pipeline_fetch_recovery.ProcessLoss,
        )
        if prefix < PUBLICATION_MUTATIONS
        else contextlib.nullcontext()
    ):
        tests.helpers.factories.peri_scribe.fires.derived_layers.publish_pair(
            directory,
            2,
        )


def writer_prefixes(
    directory: pathlib.Path,
    contracts: dict[
        bool,
        tests.formal.helpers.paths.Contract[
            tests.formal.helpers.geography_paths.ReaderProjection,
        ],
    ],
    checksums: dict[str, int],
    parents: dict[str, int],
) -> int:
    """Continue real interrupted publication into locked downstream authentication.

    Args:
        directory: The isolated scenario tree and canonical GeoPackages.
        contracts: Missing-pair policies retaining the complete checked graph.
        checksums: Exact canonical content identities.
        parents: Differential generation identities bound to full-file checksums.

    Returns:
        Number of writer-prefix/read histories checked without reseeding the matcher.
    """
    count = 0
    for initial, tolerant, prefix in itertools.product(
        (0, 1),
        (False, True),
        range(PUBLICATION_MUTATIONS + 1),
    ):
        year = directory / "writers" / str(count)
        files = tests.formal.helpers.geography_paths.Files(
            directory=year,
            templates=directory / "templates",
            checksums=checksums,
            parents=parents,
        )
        if initial:
            shutil.copytree(files.templates / str(initial), year)
        observer = tests.formal.helpers.geography_paths.Reader(
            files=files,
            checked=contracts[tolerant],
        )
        observer.observe()
        with pytest.MonkeyPatch.context() as patch:
            observer.install(patch)
            patch.setattr(spatial_data.layers, "write_geopackage", files.write)
            stop_publication_after(patch, files, prefix)
            with peri_scribe.pipeline_state.run_lock(year) as acquired:
                assert acquired
                observer.writer = True
                observer.observe("AcquireWriter")
                with pytest.raises(RuntimeError, match="writer owns"):
                    contextvars.Context().run(
                        peri_scribe.fires.derived_layers.read_derived_layers,
                        year,
                        tolerate_missing=tolerant,
                    )
                if prefix:
                    publish_prefix(year, prefix)
            observer.writer = False
            observer.observe("ReleaseWriter")
            refused = prefix in {1, 2, 3} or (
                prefix == 0 and not initial and not tolerant
            )
            with (
                pytest.raises((RuntimeError, FileNotFoundError))
                if refused
                else contextlib.nullcontext()
            ):
                result = peri_scribe.fires.derived_layers.read_derived_layers(
                    year,
                    tolerate_missing=tolerant,
                )
                expected = [] if not initial and not prefix else [2 if prefix else 1]
                if expected:
                    assert result.perimeters.revision.tolist() == expected
                else:
                    assert result.perimeters.empty
        count += 1
    return count


def stop_publication_after(
    patch: pytest.MonkeyPatch,
    files: tests.formal.helpers.geography_paths.Files,
    prefix: int,
) -> None:
    """Interrupt only after the actual selected public-file replacement completes.

    Args:
        patch: The isolated fault scope.
        files: Actual production destinations.
        prefix: Number of independently published bytes/signatures before process loss.
    """
    original = pathlib.Path.replace
    destinations = tuple(
        value
        for path in files.paths
        for value in (
            path,
            peri_scribe.fires.reuse.signature_path(path),
        )
    )

    def replace(path: pathlib.Path, target: pathlib.Path) -> pathlib.Path:
        """Keep observation and publication intact before simulating process loss.

        Args:
            path: The complete staged file.
            target: Its real public destination.

        Returns:
            The actual filesystem replacement result.

        Raises:
            ProcessLoss: Immediately after the selected durable mutation.
        """
        result = original(path, target)
        if 0 < prefix < len(destinations) and target == destinations[prefix - 1]:
            raise tests.helpers.doubles.peri_scribe.pipeline_fetch_recovery.ProcessLoss
        return result

    patch.setattr(pathlib.Path, "replace", replace)
