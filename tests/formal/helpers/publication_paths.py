"""Bind geography publication edges to exact public bytes and raw metadata."""

from __future__ import annotations

import dataclasses
import pathlib
import re
import typing

import peri_scribe.fires.files
import peri_scribe.fires.reuse
import peri_scribe.pipeline_stages
import peri_scribe.pipeline_state
import tests.formal.helpers.geography_paths
import tests.formal.helpers.paths
import tests.formal.helpers.tlc
import tests.helpers.doubles.peri_scribe.pipeline_fetch_recovery


if typing.TYPE_CHECKING:
    import pytest


type Signature = tuple[int, int, bool, bool]
type Projection = tuple[int, int, Signature, Signature, bool]


def signature(value: str) -> Signature:
    """Preserve each independently checked metadata field in the projection.

    Args:
        value: A TLC signature record.

    Returns:
        Its checksum, dependency identity, version validity, and layer completeness.
    """
    fields = dict(re.findall(r"(\w+) \|-> (TRUE|FALSE|\d+)", value))
    return (
        int(fields["checksum"]),
        int(fields["generation"]),
        fields["validVersion"] == "TRUE",
        fields["completeLayers"] == "TRUE",
    )


def contract(
    graph: tests.formal.helpers.tlc.Graph,
    *,
    forced: bool,
) -> tests.formal.helpers.paths.Contract[Projection]:
    """Only actual crashes and source changes may cross lifecycle boundaries.

    Args:
        graph: Complete checked publication graph.
        forced: The fixed caller policy for this history.

    Returns:
        The continuously matched physical publication protocol.
    """
    return tests.formal.helpers.paths.Contract(
        graph=graph,
        values={
            node: (
                int(state["fullBytes"]),
                int(state["differentialBytes"]),
                signature(state["fullSignature"]),
                signature(state["differentialSignature"]),
                state["pending"] == "TRUE",
            )
            for node, state in graph.states.items()
            if (state["forced"] == "TRUE") == forced
        },
        actions={
            edge: edge.action for edges in graph.outgoing.values() for edge in edges
        },
        internal=frozenset({
            "CheckFull",
            "WriteFullBytes",
            "WriteFullMetadata",
            "CheckDifferential",
            "WriteDifferentialBytes",
            "WriteDifferentialMetadata",
            "Acknowledge",
        }),
    )


@dataclasses.dataclass(kw_only=True)
class Observer:
    """Keep one matcher across real failures, retries, and a later source generation."""

    files: tests.formal.helpers.geography_paths.Files
    checked: tests.formal.helpers.paths.Contract[Projection]
    execution: tests.formal.helpers.paths.Path[Projection] | None = None
    target: int = 1
    failure: tuple[int, bool] | None = None
    triggered: bool = False
    replacements: list[int] = dataclasses.field(default_factory=list)
    changing_source: bool = False

    def metadata(self, path: pathlib.Path, *, differential: bool) -> Signature:
        """Read raw retained metadata even when production authentication rejects it.

        Args:
            path: The public geometry artifact.
            differential: Whether dependency identity names the full-file checksum.

        Returns:
            Independently retained metadata fields.
        """
        metadata = tests.formal.helpers.geography_paths.signature(path)
        assert metadata is not None
        generation = typing.cast("str", metadata.generation)
        layers = peri_scribe.fires.files.FULL_LAYER_NAMES
        return (
            self.files.checksums[metadata.checksum],
            self.files.parents[generation] if differential else int(generation),
            metadata.version == peri_scribe.fires.reuse.CACHE_VERSION,
            metadata.layers == (layers[:2] if differential else layers),
        )

    def snapshot(self) -> Projection:
        """No expected output or model state is used to classify concrete files.

        Returns:
            Complete public byte identities, raw signatures, and pending geography.
        """
        full, differential = self.files.paths
        return (
            self.files.revision(full),
            self.files.revision(differential),
            self.metadata(full, differential=False),
            self.metadata(differential, differential=True),
            peri_scribe.pipeline_stages.Stage.GEOGRAPHY
            in peri_scribe.pipeline_state.read_state(self.files.directory).remaining,
        )

    def observe(self) -> None:
        """Observe each completed persistent effect in its actual order."""
        value = self.snapshot()
        if self.execution is None:
            self.execution = self.checked.start(value)
        elif self.changing_source:
            self.execution = self.execution.transition("NewGeneration", value)
            self.changing_source = False
        else:
            self.execution = self.execution.observe(value)

    def interrupt(self, position: int, *, after: bool) -> None:
        """Inject process loss before or after one selected real durable replacement.

        Args:
            position: Full bytes, full metadata, growth bytes, growth metadata, or ack.
            after: Whether the selected effect has already completed.

        Raises:
            ProcessLoss: At the single requested interruption boundary.
        """
        if self.failure == (position, after) and not self.triggered:
            self.triggered = True
            raise tests.helpers.doubles.peri_scribe.pipeline_fetch_recovery.ProcessLoss

    def install(self, patch: pytest.MonkeyPatch) -> None:
        """Wrap the real replacement primitive without replacing publication logic.

        Args:
            patch: Isolated observer and process-loss scope.
        """
        full, differential = self.files.paths
        destinations = (
            full,
            peri_scribe.fires.reuse.signature_path(full),
            differential,
            peri_scribe.fires.reuse.signature_path(differential),
            peri_scribe.pipeline_state.state_path(self.files.directory),
        )
        original = pathlib.Path.replace

        def replace(path: pathlib.Path, target: pathlib.Path) -> pathlib.Path:
            """A pending-marker rewrite is an ack only when geography is removed.

            Args:
                path: Complete production staging file.
                target: Its public destination.

            Returns:
                The unchanged real replacement result.
            """
            position = destinations.index(target) if target in destinations else None
            if position == len(destinations) - 1:
                state = peri_scribe.pipeline_state.PendingRun.model_validate_json(
                    path.read_bytes(),
                )
                if peri_scribe.pipeline_stages.Stage.GEOGRAPHY in state.remaining:
                    position = None
            if position is not None:
                self.interrupt(position, after=False)
            result = original(path, target)
            if target in destinations:
                self.observe()
            if position is not None:
                self.replacements.append(position)
                self.interrupt(position, after=True)
            return result

        patch.setattr(pathlib.Path, "replace", replace)
