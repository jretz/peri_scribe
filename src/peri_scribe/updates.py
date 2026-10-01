"""Publish a static viewer and a recent snapshot of the fire-update log."""

import collections.abc
import compression.zstd
import contextlib
import datetime
import importlib.resources
import pathlib
import tempfile
import typing

import pydantic

import peri_scribe.fire_update_records
import peri_scribe.fire_updates
import peri_scribe.log_reading
import peri_scribe.paths
import peri_scribe.presentation.fire_data
import peri_scribe.presentation.selection
import peri_scribe.previews
import peri_scribe.publication
import peri_scribe.report.gathering
from measurement_units import units


WINDOW = datetime.timedelta(hours=48)
type HistoryIdentity = peri_scribe.fire_update_records.HistoryIdentity
Acreage = peri_scribe.fire_update_records.Acreage


class LogEntry(peri_scribe.fire_update_records.Record):
    """Only complete, dated log records can contribute to the published snapshot."""

    timestamp: pydantic.AwareDatetime
    batch_id: str | None = None

    def identity(self) -> peri_scribe.presentation.selection.AreaKey:
        """Retain a fire's acreage history when its current display name changes.

        Returns:
            The stable logged key, or the identifier/name key of an older record.
        """
        return self.log_identity or peri_scribe.presentation.selection.fire_area_key(
            self.identifier,
            self.name,
        )


class Update(LogEntry):
    """Carry previous acreage independently of the visible time window."""

    previous_mapped_area: Acreage | None
    history_identity: HistoryIdentity | None = None
    preview: str | None = pydantic.Field(
        default=None,
        pattern=r"^data:image/webp;base64,[A-Za-z0-9+/]+={0,2}$",
        exclude_if=lambda value: value is None,
    )


class Snapshot(pydantic.BaseModel):
    """Keep the generation time distinct from the browser's live aging clock."""

    model_config = pydantic.ConfigDict(frozen=True, extra="forbid")

    version: typing.Literal[1] = 1
    generated_at: pydantic.AwareDatetime
    updates: tuple[Update, ...]


def read_entries(year_directory: pathlib.Path) -> tuple[LogEntry, ...]:
    """Read the fire-update series, including history preserved by monthly rotation.

    Args:
        year_directory: The year directory holding the fire-update logs.

    Returns:
        Validated records in logical occurrence order, ready for stable chronological
        selection. Archived prefixes precede later plain tails even at equal timestamps.
    """
    directory = year_directory / "logs"
    records = []
    with peri_scribe.log_reading.read_lock(directory):
        paths = set(directory.glob("????-??-fire-updates.jsonl"))
        paths.update(
            path.with_suffix("")
            for path in directory.glob("????-??-fire-updates.jsonl.zst")
        )
        for path in sorted(paths):
            with contextlib.suppress(FileNotFoundError):
                for component in peri_scribe.log_reading.log_components(path):
                    opener = (
                        compression.zstd.open if component.suffix == ".zst" else open
                    )
                    with opener(component, "rt", encoding="utf-8") as stream:
                        records.extend(
                            LogEntry.model_validate_json(line)
                            for line in stream
                            if line.strip()
                        )
    return tuple(records)


def snapshot_from_entries(
    entries: collections.abc.Iterable[LogEntry],
    generated_at: datetime.datetime,
    *,
    owners: collections.abc.Mapping[str, str] | None = None,
) -> Snapshot:
    """Compare updates within their current history group before applying the window.

    Args:
        entries: The complete retained log history, possibly out of time order.
        generated_at: The aware generation time defining the initial 48-hour window.
        owners: Current owners of immutable log buckets, encoded as JSON identity pairs.

    Returns:
        Every nonzero change in the window, including downward corrections.
    """
    now = generated_at.astimezone(datetime.UTC)
    identity_parser = pydantic.TypeAdapter(HistoryIdentity)
    projected: dict[tuple[str, str], HistoryIdentity] = {
        identity_parser.validate_json(bucket): identity_parser.validate_json(owner)
        for bucket, owner in (owners or {}).items()
    }
    previous_by_fire: dict[tuple[str, str], LogEntry] = {}
    updates = []
    for entry in sorted(entries, key=lambda record: record.timestamp):
        timestamp = entry.timestamp.astimezone(datetime.UTC)
        if timestamp > now:
            continue
        history_identity = projected.get(entry.identity())
        identity = history_identity or entry.identity()
        previous = previous_by_fire.get(identity)
        previous_by_fire[identity] = entry
        previous_area = (
            previous.mapped_area.quantity() if previous is not None else 0 * units.acres
        )
        if now - WINDOW < timestamp and entry.mapped_area.quantity() != previous_area:
            updates.append(
                Update(
                    **entry.model_dump(),
                    previous_mapped_area=(
                        previous.mapped_area if previous is not None else None
                    ),
                    history_identity=history_identity,
                ),
            )
    return Snapshot(generated_at=now, updates=tuple(updates))


def write_html(path: pathlib.Path) -> None:
    """Publish the packaged viewer only when its content differs from the output.

    Args:
        path: The HTML file beside the KMZ and JSON snapshot.
    """
    content = (
        importlib.resources.files("peri_scribe").joinpath("updates.html").read_bytes()
    )
    if path.exists() and path.read_bytes() == content:
        return
    path.parent.mkdir(parents=True, exist_ok=True)
    with tempfile.TemporaryDirectory(dir=path.parent) as directory:
        temporary = pathlib.Path(directory) / path.name
        temporary.write_bytes(content)
        temporary.replace(path)


def with_previews(
    snapshot: Snapshot,
    fires: collections.abc.Sequence[peri_scribe.presentation.fire_data.FireSummary],
    *,
    state: peri_scribe.fire_updates.State | None = None,
) -> Snapshot:
    """Reuse each current fire's preview across its visible log occurrences.

    Args:
        snapshot: Chronological updates with current history ownership already applied.
        fires: The same prepared fires used to produce the completed KMZ.
        state: Saved alias-to-bucket assignments and current history owners.

    Returns:
        The snapshot with available previews, preserving all logged fields and order.
    """
    aliases = state.aliases if state is not None else {}
    owners = state.owners if state is not None else {}
    by_identity = {}
    for fire in sorted(fires, key=peri_scribe.fire_updates.mapping_priority):
        for encoded in peri_scribe.fire_updates.identity_keys(fire):
            bucket = aliases.get(encoded, encoded)
            owner = owners.get(bucket, bucket)
            by_identity[
                peri_scribe.fire_update_records.IDENTITY.validate_json(owner)
            ] = fire
    previews: dict[peri_scribe.presentation.selection.AreaKey, str | None] = {}
    updates = []
    for update in snapshot.updates:
        identity = update.history_identity or update.identity()
        fire = by_identity.get(identity)
        if fire is None:
            updates.append(update)
            continue
        key = peri_scribe.report.gathering.fire_identity(fire)
        if key not in previews:
            previews[key] = peri_scribe.previews.fire_preview(fire)
        updates.append(update.model_copy(update={"preview": previews[key]}))
    return snapshot.model_copy(update={"updates": tuple(updates)})


def write_updates_page(
    year_directory: pathlib.Path,
    *,
    fires: collections.abc.Sequence[
        peri_scribe.presentation.fire_data.FireSummary
    ] = (),
) -> None:
    """Refresh both outputs after a completed KMZ run has appended its log entries.

    Args:
        year_directory: The year directory holding the completed KMZ and logs.
        fires: Prepared KMZ fires supplying the latest preview for each visible fire.
    """
    state = peri_scribe.fire_updates.read_authoritative(
        peri_scribe.fire_updates.state_path(year_directory),
        peri_scribe.fire_updates.State,
    )
    snapshot = snapshot_from_entries(
        read_entries(year_directory),
        datetime.datetime.now(datetime.UTC),
        owners=state.owners if state is not None else None,
    )
    snapshot = with_previews(snapshot, fires, state=state)
    directory = year_directory / peri_scribe.paths.MAPS_DIRECTORY_NAME
    write_html(directory / "updates.html")
    peri_scribe.publication.write_state(directory / "updates.json", snapshot)
