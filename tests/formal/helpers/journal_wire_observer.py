"""Observe each real durable file in the builder's journal protocol.

Design notes:
[Verification evidence and execution](../../../docs/algorithms/verification-tooling.md).
"""

import collections
import collections.abc
import compression.zstd
import dataclasses
import datetime
import pathlib
import zipfile

import peri_scribe.fire_updates
import peri_scribe.paths
import peri_scribe.publication
import peri_scribe.updates
import tests.formal.helpers.journal
import tests.helpers.doubles.attribute_overrides


type Projection = tuple[int, int, int, int, int, tuple[int, ...], tuple[int, ...], bool]
GENERATION_COUNT = 2
RECORDS_PER_GENERATION = 2


class ProcessLoss(BaseException):
    """Interrupt the caller outside ordinary exception handlers."""


@dataclasses.dataclass(kw_only=True)
class Scenario:
    """Track the prepared generations and actual times needed to read artifacts."""

    directory: pathlib.Path
    generation: int = 1
    states: dict[int, peri_scribe.fire_updates.State] = dataclasses.field(
        default_factory=dict,
    )
    timestamps: dict[int, datetime.datetime] = dataclasses.field(default_factory=dict)
    batch_ids: dict[int, str] = dataclasses.field(default_factory=dict)
    viewer_times: dict[datetime.datetime, int] = dataclasses.field(default_factory=dict)

    def collection(self) -> peri_scribe.publication.Collection:
        """Identify the fixture's source inventory with its publication generation.

        Returns:
            The ordered input inventory for this fixture generation.
        """
        return peri_scribe.publication.Collection(
            files={
                str(self.generation): peri_scribe.publication.FileStamp(
                    size=self.generation,
                    modified_nanoseconds=self.generation,
                ),
            },
        )

    def observe_preparation(
        self,
        updates: peri_scribe.fire_updates.PreparedUpdates,
    ) -> None:
        """Recognize future checkpoints only after the real prior journal is cleared.

        Args:
            updates: The prepared records and checkpoint before native publication.
        """
        assert not peri_scribe.fire_updates.pending_path(self.directory).exists()
        self.states[self.generation] = updates.state

    def number(self, state: peri_scribe.fire_updates.State | None) -> int:
        """Recognize checkpoint contents by the actual prepared state payload.

        Args:
            state: The deserialized pending or acknowledged checkpoint.

        Returns:
            Its prepared generation, or zero when absent.
        """
        if state is None:
            return 0
        return next(number for number, value in self.states.items() if value == state)

    def log_entry(self, generation: int, number: int) -> peri_scribe.updates.LogEntry:
        """Specify the frozen payload for each occurrence in a fixture batch.

        Args:
            generation: The publication that originally observed the mapping.
            number: The fire within that publication's batch.

        Returns:
            A complete log occurrence with its original preview and journal metadata.
        """
        return peri_scribe.updates.LogEntry(
            timestamp=self.timestamps[generation],
            identifier=f"fire-{number}",
            log_identity=("id", f"fire-{number}"),
            name=f"Fire {number}",
            location=None,
            batch_id=self.batch_ids[generation],
            mapped_area=peri_scribe.updates.Acreage(value=100 * generation + number),
            preview=tests.formal.helpers.journal.PREVIEWS[generation - 1],
        )

    def log_counts(self, *, compressed: bool) -> tuple[int, ...]:
        """Validate record pairs and timestamp retention while reading actual logs.

        Args:
            compressed: Whether to project archive copies or plain copies.

        Returns:
            Physical batch counts for each generation in the model.
        """
        grouped: dict[int, list[peri_scribe.updates.LogEntry]] = (
            collections.defaultdict(
                list,
            )
        )
        pattern = "*-fire-updates.jsonl.zst" if compressed else "*-fire-updates.jsonl"
        opener = compression.zstd.open if compressed else open
        for path in (self.directory / "logs").glob(pattern):
            with opener(path, "rt", encoding="utf-8") as stream:
                for line in stream:
                    entry = peri_scribe.updates.LogEntry.model_validate_json(line)
                    generation = int(entry.mapped_area.value) // 100
                    grouped[generation].append(entry)
        result = []
        for generation in (1, 2):
            entries = grouped[generation]
            assert len(entries) in {0, RECORDS_PER_GENERATION}
            if entries:
                assert entries == [
                    self.log_entry(generation, number)
                    for number in range(RECORDS_PER_GENERATION)
                ]
            result.append(len(entries) // 2)
        return tuple(result)

    def snapshot(self) -> Projection:
        """Decode independently durable files without inventing abstract transitions.

        Returns:
            The real artifact generations, log multiplicities, and receipt presence.
        """
        pending = peri_scribe.publication.read_state(
            peri_scribe.fire_updates.pending_path(self.directory),
            peri_scribe.fire_updates.PendingUpdates,
        )
        journal = self.number(pending.state) if pending is not None else 0
        if pending is not None:
            self.timestamps.setdefault(journal, pending.timestamp)
            assert pending.timestamp == self.timestamps[journal]
            self.batch_ids.setdefault(journal, pending.batch_id)
            assert pending.batch_id == self.batch_ids[journal]
        checkpoint = self.number(
            peri_scribe.publication.read_state(
                peri_scribe.fire_updates.state_path(self.directory),
                peri_scribe.fire_updates.State,
            ),
        )
        kmz = 0
        path = peri_scribe.paths.kmz_path(self.directory)
        if path.exists():
            with zipfile.ZipFile(path) as archive:
                kmz = int(archive.read("doc.kml").decode().split('"')[1])
        publication = peri_scribe.publication.read_state(
            peri_scribe.publication.publication_path(self.directory),
            peri_scribe.publication.Publication,
        )
        published = int(next(iter(publication.files))) if publication is not None else 0
        viewer = peri_scribe.publication.read_state(
            self.directory / "maps" / "updates.json",
            peri_scribe.updates.Snapshot,
        )
        displayed = self.viewer_times[viewer.generated_at] if viewer is not None else 0
        if viewer is not None:
            assert viewer.updates == self.viewer_records(displayed, viewer.generated_at)
        return (
            kmz,
            published,
            journal,
            checkpoint,
            displayed,
            self.log_counts(compressed=False),
            self.log_counts(compressed=True),
            any((self.directory / "logs").glob("*.jsonl.rotation.json")),
        )

    def viewer_records(
        self,
        generation: int,
        now: datetime.datetime,
    ) -> tuple[peri_scribe.updates.Update, ...]:
        """Specify complete viewer payloads independently of the production fold.

        Args:
            generation: The mapping checkpoint at this viewer's publication.
            now: Its recorded generation time, separate from later retries.

        Returns:
            The visible fixture batches with each fire's prior acreage and identity.
        """
        return tuple(
            peri_scribe.updates.Update(
                **self.log_entry(batch, number).model_dump(),
                history_identity=("id", f"fire-{number}"),
                previous_mapped_area=(
                    peri_scribe.updates.Acreage(value=100 * (batch - 1) + number)
                    if batch > 1
                    else None
                ),
            )
            for batch in range(1, generation + 1)
            if now - datetime.timedelta(hours=48) < self.timestamps[batch] <= now
            for number in range(RECORDS_PER_GENERATION)
        )


def boundary(
    monkeypatch: tests.helpers.doubles.attribute_overrides.AttributePatch,
    inspect: collections.abc.Callable[[], None],
    target: pathlib.Path | None,
    *,
    unlink: bool = False,
    after: bool = True,
) -> None:
    """Interrupt before or after one actual atomic replacement or deletion.

    Args:
        monkeypatch: Scoped replacement of filesystem methods.
        inspect: Check the real observation on either side of a durable operation.
        target: Exact destination at which to interrupt, or None to observe only.
        unlink: Whether the selected boundary is a deletion.
        after: Whether the selected file mutation succeeds before process loss.
    """
    original_replace = pathlib.Path.replace
    original_unlink = pathlib.Path.unlink

    def replace(path: pathlib.Path, destination: pathlib.Path) -> pathlib.Path:
        """Preserve the real atomic replacement and inspect both sides.

        Args:
            path: Temporary file being published.
            destination: Public destination path.

        Returns:
            The destination returned by pathlib.

        Raises:
            ProcessLoss: At the selected interruption boundary.
        """
        inspect()
        if destination == target and not unlink and not after:
            raise ProcessLoss
        result = original_replace(path, destination)
        inspect()
        if destination == target and not unlink and after:
            raise ProcessLoss
        return result

    def remove(path: pathlib.Path, *, missing_ok: bool = False) -> None:
        """Keep archive and journal cleanup visible as separate durable actions.

        Args:
            path: File being removed.
            missing_ok: Whether absence is accepted by the real caller.

        Raises:
            ProcessLoss: At the selected interruption boundary.
        """
        inspect()
        if path == target and unlink and not after:
            raise ProcessLoss
        original_unlink(path, missing_ok=missing_ok)
        inspect()
        if path == target and unlink and after:
            raise ProcessLoss

    monkeypatch.setattr(pathlib.Path, "replace", replace)
    monkeypatch.setattr(pathlib.Path, "unlink", remove)
