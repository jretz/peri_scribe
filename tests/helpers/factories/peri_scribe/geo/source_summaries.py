"""Build isolated named snapshots for authenticated summary selection tests."""

import pathlib

import peri_scribe.sources.snapshots


def snapshot(directory: pathlib.Path, serial: int, revision: int) -> pathlib.Path:
    """Write deterministic source bytes with a valid retained-snapshot filename.

    Args:
        directory: Per-test root containing the feed's source files.
        serial: Source snapshot serial.
        revision: Symbolic source revision encoded as authoritative bytes.

    Returns:
        The complete retained-snapshot path.
    """
    path = (
        directory
        / "feed"
        / peri_scribe.sources.snapshots.SourceFile(
            serial_number=serial,
            last_edit_timestamp=1,
        ).relative_path
    )
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(str(revision).encode())
    return path
