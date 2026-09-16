"""Replace reuse dependencies with controlled test doubles."""

import pathlib
import typing

import peri_scribe.fires.reuse
import peri_scribe.models


def write_partial_output_and_fail(
    path: pathlib.Path,
    _layers: list[peri_scribe.models.LayerData],
) -> None:
    """Simulate an interrupted write that leaves incomplete output.

    Args:
        path: Path supplied to the intercepted file operation.
        _layers: Layer contents accepted for writer compatibility.

    Raises:
        RuntimeError: Always, after writing partial content.
    """
    path.write_bytes(b"partial")
    message = "interrupted"
    raise RuntimeError(message)


def make_interrupted_replacement(
    *,
    path: pathlib.Path,
    replace: typing.Callable[..., pathlib.Path],
) -> typing.Callable[..., pathlib.Path]:
    """Create a callback with controlled dependencies.

    Interrupt metadata publication after the data file has been replaced.

    Args:
        path: Snapshot or output path selected for the controlled failure.
        replace: Original file replacement operation used for permitted destinations.

    Returns:
        The callback bound to the supplied dependencies.
    """

    def interrupted(source: pathlib.Path, target: pathlib.Path) -> pathlib.Path:
        """Interrupt metadata publication after the data file has been replaced.

        Args:
            source: Temporary file containing the replacement data or metadata.
            target: Destination path for the replacement operation.

        Returns:
            The destination of a successful file replacement.

        Raises:
            OSError: If the destination is the reuse-signature file.
        """
        if target == peri_scribe.fires.reuse.signature_path(path):
            message = "interrupted metadata publication"
            raise OSError(message)
        return replace(source, target)

    return interrupted
