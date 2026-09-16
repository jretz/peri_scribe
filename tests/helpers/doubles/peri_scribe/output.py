"""Replace output dependencies with controlled test doubles."""

from __future__ import annotations

import io
import pathlib
import typing

import geopandas


if typing.TYPE_CHECKING:
    import pytest


class RecordingFile:
    """In-memory file stand-in that keeps its contents after being closed."""

    def __init__(self) -> None:
        """Initialize an in-memory text file for output assertions."""
        self.stream = io.StringIO()

    def write(self, text: str) -> int:
        """Capture text written by the document serializer.

        Args:
            text: Serialized document text to capture.

        Returns:
            The number of characters written.
        """
        return self.stream.write(text)

    def getvalue(self) -> str:
        """Expose the captured document text for assertions.

        Returns:
            All text written to this recording file.
        """
        return self.stream.getvalue()

    def __enter__(self) -> typing.Self:
        """Provide the recording file to a managed write operation.

        Returns:
            This recording file.
        """
        return self

    def __exit__(
        self,
        _exc_type: object,
        _exc_value: object,
        _traceback: object,
    ) -> None:
        """Keep captured contents available after a managed write finishes.

        Args:
            _exc_type: Exception type supplied when leaving the managed write.
            _exc_value: Exception instance supplied when leaving the managed write.
            _traceback: Traceback supplied when leaving the managed write.
        """


def stub_to_file(
    monkeypatch: pytest.MonkeyPatch,
) -> list[tuple[pathlib.Path, str, str, str]]:
    """Record GeoDataFrame.to_file calls.

    Args:
        monkeypatch: The monkeypatch fixture.

    Returns:
        The recorded (path, driver, layer, mode) calls.
    """
    calls: list[tuple[pathlib.Path, str, str, str]] = []
    monkeypatch.setattr(
        geopandas.GeoDataFrame,
        "to_file",
        lambda _self, path, driver, layer, mode: calls.append((
            path,
            driver,
            layer,
            mode,
        )),
    )
    return calls


def make_unlink_recorder(*, unlinked: list[pathlib.Path]) -> typing.Callable[..., None]:
    """Create a callback to capture which existing output file is removed.

    Args:
        unlinked: Shared list recording paths selected for removal.

    Returns:
        The callback bound to the supplied dependencies.
    """

    def fake_unlink(_self: pathlib.Path) -> None:
        """Capture which existing output file is removed.

        Args:
            _self: Path receiving the intercepted filesystem operation.
        """
        unlinked.append(_self)

    return fake_unlink


def make_recording_file_opener(
    *,
    files: list[RecordingFile],
) -> typing.Callable[..., RecordingFile]:
    """Create a callback with controlled dependencies.

    Validate text-output options and provide an in-memory destination.

    Args:
        files: Shared list retaining opened recording files for content assertions.

    Returns:
        The callback bound to the supplied dependencies.
    """

    def fake_open(_self: pathlib.Path, mode: str, encoding: str) -> RecordingFile:
        """Validate text-output options and provide an in-memory destination.

        Args:
            _self: Path receiving the intercepted filesystem operation.
            mode: Requested file mode, which must be text writing.
            encoding: Requested text encoding, which must be UTF-8.

        Returns:
            A fresh recording file retained for output assertions.
        """
        assert mode == "w"
        assert encoding == "utf-8"
        file = RecordingFile()
        files.append(file)
        return file

    return fake_open
