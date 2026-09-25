"""Terminal reports are simulated without accessing the user's interactive input."""

from __future__ import annotations

import json
import os
import pty
import select
import signal
import struct
import termios
import time
import typing
import unittest.mock

import peri_scribe.terminal_images
from measurement_units import units


if typing.TYPE_CHECKING:
    import multiprocessing.connection

    import pytest


def stub_terminal(
    monkeypatch: pytest.MonkeyPatch,
    dimensions: tuple[int, int, int, int],
    reply: bytes = b"",
) -> unittest.mock.Mock:
    """Expose terminal geometry independently of the test runner's output capture.

    Args:
        monkeypatch: Restore substituted I/O after the test.
        dimensions: Rows, columns, pixel width, and pixel height.
        reply: The optional logical cell-size report.

    Returns:
        A stream suitable for exercising display sizing.
    """
    monkeypatch.setattr(os, "isatty", unittest.mock.Mock(return_value=True))
    monkeypatch.setattr(
        peri_scribe.terminal_images.fcntl,
        "ioctl",
        unittest.mock.Mock(return_value=struct.pack("HHHH", *dimensions)),
    )
    monkeypatch.setattr(
        peri_scribe.terminal_images,
        "reported_cell_size",
        unittest.mock.Mock(
            return_value=peri_scribe.terminal_images.parse_cell_size(reply),
        ),
    )
    stream = unittest.mock.Mock()
    stream.fileno.return_value = 42
    return stream


def stub_cell_reply(
    monkeypatch: pytest.MonkeyPatch,
    reply: bytes,
) -> unittest.mock.Mock:
    """Make bytewise reporting and its bounded wait deterministic.

    Args:
        monkeypatch: Restore substituted I/O after the test.
        reply: Bytes delivered by the simulated terminal, followed by EOF.

    Returns:
        The mock recording the cell-size query sent to the terminal.
    """
    writer = unittest.mock.Mock()
    monkeypatch.setattr(os, "write", writer)
    monkeypatch.setattr(
        os,
        "read",
        unittest.mock.Mock(side_effect=[bytes([value]) for value in reply] + [b""]),
    )
    monkeypatch.setattr(
        select,
        "select",
        unittest.mock.Mock(return_value=([42], [], [])),
    )
    monkeypatch.setattr(
        peri_scribe.terminal_images.time,
        "monotonic",
        unittest.mock.Mock(return_value=0),
    )
    return writer


def answer_cell_query(descriptor: int, reply: bytes) -> bytes:
    """Reply from a pseudo-terminal's host side without depending on a real emulator.

    Args:
        descriptor: The pseudo-terminal's master descriptor.
        reply: An emulator's cell-size response.

    Returns:
        The query observed from the application.
    """
    readable, _, _ = select.select([descriptor], [], [], 2)
    if not readable:
        return b""
    query = os.read(descriptor, 1024)
    os.write(descriptor, reply)
    return query


def background_query_child(descriptor: int, output: int) -> typing.NoReturn:
    """Exercise the real terminal path as a background job in an isolated session.

    Args:
        descriptor: The test's controlling terminal slave.
        output: A pipe carrying the dimensions back to the isolated supervisor.
    """
    os.setpgid(0, 0)
    signal.signal(signal.SIGTTOU, signal.SIG_DFL)
    with os.fdopen(descriptor, "w", closefd=False) as terminal:
        dimensions = peri_scribe.terminal_images.display_dimensions(
            terminal,
            1000 * units.pixels,
            1000 / 768,
        )
    os.write(output, json.dumps(dimensions).encode())
    os._exit(0)


def await_background_query(process: int) -> int:
    """Bound even a suspended child without changing the test runner's signal state.

    Args:
        process: The isolated background child.

    Returns:
        Its wait status, or its killed status after a timeout.
    """
    deadline = time.monotonic() + 2
    while time.monotonic() < deadline:
        waited, status = os.waitpid(process, os.WUNTRACED | os.WNOHANG)
        if waited:
            return status
        time.sleep(0.01)
    os.kill(process, signal.SIGKILL)
    return os.waitpid(process, 0)[1]


def background_query_result() -> dict[str, object]:
    """Own a disposable controlling terminal; the outer caller starts a new session.

    Returns:
        Whether sizing exited, its dimensions, and whether the query changed the tty.
    """
    signal.signal(signal.SIGHUP, signal.SIG_IGN)
    master, slave = pty.openpty()
    reader, writer = os.pipe()
    try:
        peri_scribe.terminal_images.fcntl.ioctl(slave, termios.TIOCSCTTY, 0)
        peri_scribe.terminal_images.fcntl.ioctl(
            slave,
            termios.TIOCSWINSZ,
            struct.pack("HHHH", 30, 80, 640, 480),
        )
        original = termios.tcgetattr(slave)
        process = os.fork()
        if not process:
            background_query_child(slave, writer)
        os.close(writer)
        status = await_background_query(process)
        if os.WIFSTOPPED(status):
            os.kill(process, signal.SIGKILL)
            os.waitpid(process, 0)
            return {"stopped_by": os.WSTOPSIG(status)}
        return {
            "exit_status": os.waitstatus_to_exitcode(status),
            "dimensions": json.loads(os.read(reader, 1024)),
            "settings_restored": termios.tcgetattr(slave) == original,
            "query_sent": bool(select.select([master], [], [], 0)[0]),
        }
    finally:
        os.close(reader)
        os.close(master)
        os.close(slave)


def isolated_background_query(output: multiprocessing.connection.Connection) -> None:
    """Keep controlling-terminal and signal changes outside the pytest process.

    Args:
        output: The spawned process's result connection.
    """
    os.setsid()
    try:
        output.send(background_query_result())
    finally:
        output.close()
