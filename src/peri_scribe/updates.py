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

import peri_scribe.paths
import peri_scribe.presentation.selection
import peri_scribe.publication
from measurement_units import units


if typing.TYPE_CHECKING:
    import pint


WINDOW = datetime.timedelta(hours=48)


class Acreage(pydantic.BaseModel):
    """Validate the log's quantity representation at the serialization boundary."""

    model_config = pydantic.ConfigDict(frozen=True, extra="forbid")

    value: float = pydantic.Field(ge=0, allow_inf_nan=False)
    units: typing.Literal["acre"] = "acre"

    def quantity(self) -> pint.Quantity:
        """Return a unit-aware value for comparisons with earlier mapping.

        Returns:
            The measured acreage as a quantity.
        """
        return self.value * units.acres


class LogEntry(pydantic.BaseModel):
    """Only complete, dated log records can contribute to the published snapshot."""

    model_config = pydantic.ConfigDict(frozen=True, extra="forbid")

    timestamp: pydantic.AwareDatetime
    identifier: str | None
    name: str
    location: str | None
    mapped_area: Acreage
    batch_id: str | None = None
    log_identity: tuple[typing.Literal["id", "name", "local"], str] | None = None

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
        Validated records in file order, ready for chronological selection.
    """
    directory = year_directory / "logs"
    paths = sorted([
        *directory.glob("????-??-fire-updates.jsonl"),
        *directory.glob("????-??-fire-updates.jsonl.zst"),
    ])
    records = []
    for path in paths:
        opener = compression.zstd.open if path.suffix == ".zst" else open
        with (
            contextlib.suppress(FileNotFoundError),
            opener(path, "rt", encoding="utf-8") as stream,
        ):
            records.extend(
                LogEntry.model_validate_json(line) for line in stream if line.strip()
            )
    return tuple(records)


def snapshot_from_entries(
    entries: collections.abc.Iterable[LogEntry],
    generated_at: datetime.datetime,
) -> Snapshot:
    """Compare each update to its own preceding log entry before applying the window.

    Args:
        entries: The complete retained log history, possibly out of time order.
        generated_at: The aware generation time defining the initial 48-hour window.

    Returns:
        Every nonzero change in the window, including downward corrections.
    """
    now = generated_at.astimezone(datetime.UTC)
    previous_by_fire: dict[tuple[str, str], LogEntry] = {}
    updates = []
    for entry in sorted(entries, key=lambda record: record.timestamp):
        timestamp = entry.timestamp.astimezone(datetime.UTC)
        if timestamp > now:
            continue
        identity = entry.identity()
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


def write_updates_page(year_directory: pathlib.Path) -> None:
    """Refresh both outputs after a completed KMZ run has appended its log entries.

    Args:
        year_directory: The year directory holding the completed KMZ and logs.
    """
    snapshot = snapshot_from_entries(
        read_entries(year_directory),
        datetime.datetime.now(datetime.UTC),
    )
    directory = year_directory / peri_scribe.paths.MAPS_DIRECTORY_NAME
    write_html(directory / "updates.html")
    peri_scribe.publication.write_state(directory / "updates.json", snapshot)
