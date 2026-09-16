"""Build inputs for snapshots tests."""

from __future__ import annotations

import pathlib

import peri_scribe.sources.snapshots
import tests.helpers.factories.peri_scribe.sources.feed_types


SAMPLE_LAST_EDIT_TIMESTAMP = 2


# The base directory fetch resolves from ``pathlib.Path.cwd()``, which is mocked to this
# value so snapshots never touch the real filesystem.
BASE_DIRECTORY = pathlib.Path("/fetch")


def snapshot_path(
    *,
    feed_name: str = (
        tests.helpers.factories.peri_scribe.sources.feed_types
    ).SAMPLE_FEED_NAME,
    serial_number: int = 0,
    last_edit_timestamp: int = SAMPLE_LAST_EDIT_TIMESTAMP,
) -> pathlib.Path:
    """Return the snapshot path fetch writes for a feed and last-edit timestamp.

    Args:
        feed_name: Feed name used in the snapshot directory.
        serial_number: Snapshot sequence number used in the bucket and filename.
        last_edit_timestamp: Layer edit timestamp in milliseconds since the Unix epoch.

    Returns:
        The snapshot path for the 2026 test year and supplied feed metadata.
    """
    return peri_scribe.sources.snapshots.source_geopackage_path(
        BASE_DIRECTORY,
        2026,
        feed_name,
        peri_scribe.sources.snapshots.SourceFile(
            serial_number=serial_number,
            last_edit_timestamp=last_edit_timestamp,
        ),
    )


def source_file(
    *,
    serial_number: int,
    last_edit_timestamp: int = 0,
) -> peri_scribe.sources.snapshots.SourceFile:
    """Return a SourceFile with *serial_number* and *last_edit_timestamp*.

    Args:
        serial_number: The source file's serial number.
        last_edit_timestamp: The source file's last-edit timestamp.

    Returns:
        The constructed source file.
    """
    return peri_scribe.sources.snapshots.SourceFile(
        serial_number=serial_number,
        last_edit_timestamp=last_edit_timestamp,
    )
