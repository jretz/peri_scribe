"""Size OSC 1337 images to the terminal's visible width with an explicit pixel cap."""

from __future__ import annotations

import dataclasses
import fcntl
import math
import os
import re
import select
import struct
import termios
import time
import tty
import typing

from measurement_units import units


if typing.TYPE_CHECKING:
    import pint


CELL_REPORT = re.compile(
    rb"\x1b\]1337;ReportCellSize=(\d+(?:\.\d+)?);(\d+(?:\.\d+)?)"
    rb"(?:;\d+(?:\.\d+)?)?(?:\x07|\x1b\\)",
)
QUERY_TIMEOUT = 250 * units.milliseconds
MAXIMUM_REPLY_BYTES = 128


@dataclasses.dataclass(frozen=True, kw_only=True)
class CellSize:
    """Reported logical cell dimensions account for high-density display scaling."""

    width: pint.Quantity
    height: pint.Quantity


def parse_cell_size(reply: bytes) -> CellSize | None:
    """Use display points from the report independently of its backing-pixel scale.

    Args:
        reply: A complete or partial OSC cell-size response.

    Returns:
        Positive logical cell dimensions, or None for an unusable response.
    """
    match = CELL_REPORT.fullmatch(reply)
    if match is None:
        return None
    height, width = float(match[1]), float(match[2])
    if not all(math.isfinite(value) and value > 0 for value in (height, width)):
        return None
    return CellSize(width=width * units.pixels, height=height * units.pixels)


def read_cell_size(descriptor: int) -> CellSize | None:
    """Bound the wait for terminals that do not implement the optional size query.

    Args:
        descriptor: A terminal in noncanonical mode with echo disabled.

    Returns:
        Its logical cell dimensions, or None when no valid report arrives.
    """
    os.write(descriptor, b"\x1b]1337;ReportCellSize\x07")
    deadline = time.monotonic() + QUERY_TIMEOUT.m_as("seconds")
    reply = bytearray()
    while len(reply) < MAXIMUM_REPLY_BYTES:
        remaining = deadline - time.monotonic()
        if remaining <= 0 or not select.select([descriptor], [], [], remaining)[0]:
            return None
        chunk = os.read(descriptor, 1)
        if not chunk:
            return None
        reply.extend(chunk)
        if reply.endswith((b"\x07", b"\x1b\\")):
            return parse_cell_size(bytes(reply))
    return None


def query_cell_size(descriptor: int) -> CellSize | None:
    """Restore terminal input settings even if reporting fails or is interrupted.

    Args:
        descriptor: A terminal open for reading and writing.

    Returns:
        Its reported logical cell dimensions, if available.
    """
    # Avoid consuming input already queued before this command's brief query.
    if select.select([descriptor], [], [], 0)[0]:
        return None
    # A background job must not change the foreground shell's input mode.
    if os.tcgetpgrp(descriptor) != os.getpgrp():
        return None
    original = termios.tcgetattr(descriptor)
    try:
        tty.setcbreak(descriptor, termios.TCSANOW)
        # Canonical mode hides an unfinished line from select until its newline.
        # Leave that newly visible input queued for the shell and skip the query.
        if select.select([descriptor], [], [], 0)[0]:
            return None
        return read_cell_size(descriptor)
    finally:
        termios.tcsetattr(descriptor, termios.TCSANOW, original)


def fitted_dimensions(
    columns: int,
    cell: CellSize,
    maximum_width: pint.Quantity,
    aspect_ratio: float,
) -> tuple[str, str]:
    """Leave one column of margin and keep the displayed width under the pixel cap.

    Args:
        columns: Available terminal columns.
        cell: Its display-cell dimensions.
        maximum_width: The maximum visible image width.
        aspect_ratio: The image width divided by its height.

    Returns:
        OSC width and height expressed in character cells.
    """
    width = max(1, min(columns - 1, math.floor(maximum_width / cell.width)))
    height = math.ceil((width * cell.width / cell.height).magnitude / aspect_ratio)
    return str(width), str(height)


def reported_cell_size(descriptor: int) -> CellSize | None:
    """Query the output terminal even when standard input is redirected.

    Args:
        descriptor: The image's output terminal.

    Returns:
        Logical cell dimensions, or None when terminal access is unavailable.
    """
    try:
        with os.fdopen(
            os.open(os.ttyname(descriptor), os.O_RDWR | os.O_NOCTTY),
            "r+b",
            buffering=0,
        ) as terminal:
            return query_cell_size(terminal.fileno())
    except OSError, ValueError, termios.error:
        return None


def terminal_dimensions(
    descriptor: int,
    maximum_width: pint.Quantity,
    aspect_ratio: float,
) -> tuple[str, str] | None:
    """Prefer logical cell measurements over the OS's optional pixel dimensions.

    Args:
        descriptor: The image's output terminal.
        maximum_width: The maximum visible image width.
        aspect_ratio: The image width divided by its height.

    Returns:
        Character-cell dimensions, or None when pixel sizing is unavailable.
    """
    rows, columns, pixel_width, pixel_height = struct.unpack(
        "HHHH",
        fcntl.ioctl(descriptor, termios.TIOCGWINSZ, bytes(8)),
    )
    if columns <= 1:
        return None
    cell = reported_cell_size(descriptor)
    if cell is None and rows and pixel_width and pixel_height:
        cell = CellSize(
            width=pixel_width / columns * units.pixels,
            height=pixel_height / rows * units.pixels,
        )
    if cell is None or cell.width > maximum_width:
        return None
    return fitted_dimensions(columns, cell, maximum_width, aspect_ratio)


def display_dimensions(
    stream: typing.TextIO,
    maximum_width: pint.Quantity,
    aspect_ratio: float,
) -> tuple[str, str]:
    """Fit live terminals while keeping redirected output independent of a TTY.

    Args:
        stream: The destination for the inline image.
        maximum_width: The maximum visible width, in logical pixels when reported.
        aspect_ratio: The image width divided by its height.

    Returns:
        Width and height controls; explicit pixel dimensions are the fallback.
    """
    width = int(maximum_width.m_as("pixels"))
    fallback = (f"{width}px", f"{round(width / aspect_ratio)}px")
    try:
        descriptor = stream.fileno()
        if not os.isatty(descriptor):
            return fallback
        return terminal_dimensions(descriptor, maximum_width, aspect_ratio) or fallback
    except OSError, ValueError, termios.error:
        return fallback
