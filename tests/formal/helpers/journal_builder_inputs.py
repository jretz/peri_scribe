"""Carry immutable prepared inputs into fresh builder persistence processes."""

import contextlib
import dataclasses
import datetime
import pathlib
import typing

import pydantic
import time_machine

import peri_scribe.fire_updates
import peri_scribe.kml.persistence
import peri_scribe.paths
import peri_scribe.preparation
import peri_scribe.updates


if typing.TYPE_CHECKING:
    import tests.formal.helpers.journal_wire_observer


CATALOGUE_NAME = "builder-inputs.json"
PREPARED = pydantic.TypeAdapter(peri_scribe.fire_updates.PreparedUpdates)


@dataclasses.dataclass(frozen=True, kw_only=True)
class Entry:
    """One prepared batch keyed by input generation and validated prior state."""

    generation: int
    previous: str
    updates: str


class Catalogue(pydantic.BaseModel):
    """Fixture inputs observed through current full builder preparation."""

    model_config = pydantic.ConfigDict(
        frozen=True,
        extra="forbid",
        ser_json_bytes="base64",
        val_json_bytes="base64",
    )

    entries: tuple[Entry, ...]
    documents: tuple[str, ...]
    images: tuple[tuple[str, bytes], ...]

    def prepare(
        self,
        generation: int,
        previous: peri_scribe.fire_updates.State,
    ) -> peri_scribe.fire_updates.PreparedUpdates:
        """Select the one prepared input matching the actually recovered checkpoint.

        Args:
            generation: The current fixture's source generation.
            previous: The baseline read after native recovery in this interpreter.

        Returns:
            A newly decoded batch for the current publication.
        """
        (entry,) = (
            entry
            for entry in self.entries
            if entry.generation == generation
            and peri_scribe.fire_updates.State.model_validate_json(entry.previous)
            == previous
        )
        return PREPARED.validate_json(entry.updates)


def keep_snapshot(
    snapshot: peri_scribe.updates.Snapshot,
    _state: peri_scribe.fire_updates.State | None,
) -> peri_scribe.updates.Snapshot:
    """Keep the fixture's recorded previews and locations as validated at preparation.

    Args:
        snapshot: The snapshot folded from this interpreter's actual logs.
        _state: The actual mapping checkpoint already used to select the snapshot.

    Returns:
        The viewer snapshot with its fixture fields already recorded.
    """
    return snapshot


def publish_fixture(
    scenario: tests.formal.helpers.journal_wire_observer.Scenario,
    now: datetime.datetime,
    catalogue_path: pathlib.Path,
) -> None:
    """Run the actual persistence command against inputs prepared in this run.

    Args:
        scenario: Private state used to interpret durable boundaries in this process.
        now: The time of publication and log rotation.
        catalogue_path: The immutable inputs from the current full fixture setup.
    """
    catalogue = Catalogue.model_validate_json(catalogue_path.read_bytes())
    directory = scenario.directory
    generation = scenario.generation
    scenario.viewer_times[now] = generation
    collection = scenario.collection()

    def prepare(
        previous: peri_scribe.fire_updates.State,
    ) -> peri_scribe.fire_updates.PreparedUpdates:
        """Look up inputs only after the prior durable update has recovered.

        Args:
            previous: The validated baseline read by the publication command.

        Returns:
            The exact prepared batch for that baseline.
        """
        updates = catalogue.prepare(generation, previous)
        scenario.observe_preparation(updates)
        return updates

    def write_document(stream: typing.TextIO) -> int:
        """Stream this fixture's actual prepared document into the archive.

        Args:
            stream: The document member's text stream.

        Returns:
            The count of characters written.
        """
        return stream.write(catalogue.documents[generation - 1])

    with time_machine.travel(now, tick=False), peri_scribe.preparation.scope(directory):
        peri_scribe.kml.persistence.publish(
            directory,
            peri_scribe.paths.kmz_path(directory),
            write_document=lambda: write_document,
            images=dict(catalogue.images),
            checkpoint=(collection, {}),
            prepare=prepare,
            write_viewer=lambda year: peri_scribe.updates.write_snapshot(
                year,
                decorate=keep_snapshot,
            ),
            archive_phase=contextlib.nullcontext,
        )
