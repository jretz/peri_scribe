"""Keep the filesystem operations for durable pipeline markers together.

Algorithm reasoning and contracts:
[Pipeline publication](../../docs/algorithms/pipeline-publication.md)
"""

from __future__ import annotations

import dataclasses
import pathlib
import tempfile
import typing


class File(typing.Protocol):
    """Expose one file's operations so callers can retain their own recovery rules."""

    def read_bytes(self) -> bytes:
        """Return the bytes available for validation by the caller."""
        ...

    def replace_text(self, text: str) -> None:
        """Replace the file only after its complete text is available.

        Args:
            text: The serialized state to persist.
        """
        ...

    def exists(self) -> bool:
        """Return whether this file is visible to a reader."""
        ...

    def touch(self) -> None:
        """Ensure the marker and its parent directory exist."""
        ...

    def remove(self, *, missing_ok: bool) -> None:
        """Remove the marker to revoke what it represented.

        Args:
            missing_ok: Whether an absent marker already satisfies the request.
        """
        ...

    def identity(self) -> tuple[int, int]:
        """Return the file size in bytes and modification time in nanoseconds."""
        ...


@dataclasses.dataclass(frozen=True, kw_only=True)
class LocalFile(File):
    """Use the local filesystem as the authority for durable effects.

    Args:
        path: The file observed or changed by each operation.
    """

    path: pathlib.Path

    @typing.override
    def read_bytes(self) -> bytes:
        """Read the current bytes so callers observe external changes.

        Returns:
            The complete file contents.
        """
        return self.path.read_bytes()

    @typing.override
    def replace_text(self, text: str) -> None:
        """Stage within the same filesystem before replacing the live state.

        Args:
            text: The serialized state to persist.
        """
        self.path.parent.mkdir(parents=True, exist_ok=True)
        with tempfile.TemporaryDirectory(dir=self.path.parent) as directory:
            temporary = pathlib.Path(directory) / self.path.name
            temporary.write_text(text)
            temporary.replace(self.path)

    @typing.override
    def exists(self) -> bool:
        """Check the current marker path for readers.

        Returns:
            Whether the marker exists.
        """
        return self.path.exists()

    @typing.override
    def touch(self) -> None:
        """Record a marker even if this is the first write in its directory."""
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self.path.touch()

    @typing.override
    def remove(self, *, missing_ok: bool) -> None:
        """Unlink this marker so a prior checkpoint cannot authorize a skip.

        Args:
            missing_ok: Whether an absent marker already satisfies the request.
        """
        self.path.unlink(missing_ok=missing_ok)

    @typing.override
    def identity(self) -> tuple[int, int]:
        """Take both identity fields from one observation of the file.

        Returns:
            The file size in bytes and modification time in nanoseconds.
        """
        status = self.path.stat()
        return status.st_size, status.st_mtime_ns


def at(path: pathlib.Path) -> File:
    """Bind effects to the path selected by the caller.

    Args:
        path: The destination or source chosen by the caller.

    Returns:
        A file with local filesystem semantics.
    """
    return LocalFile(path=path)
